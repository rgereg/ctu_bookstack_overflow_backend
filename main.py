from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from pydantic import BaseModel
from jose import jwt
from typing import Optional
import os
import requests  # CHANGED: added to fetch Supabase JWKS (public keys) for ES256 token verification


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # CHANGED: added service_role env var

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

supabase_service = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)  # CHANGED: added service_role client (server-only)

origins = [
    "http://localhost:5500",
    "https://rgereg.github.io"
]

app = FastAPI()

@app.middleware("http")
async def debug_requests(request, call_next):
    print(
        ">",
        request.method,
        request.url.path,
        ">auth:",
        "YES" if request.headers.get("authorization") else "NO"
    )
    response = await call_next(request)
    print("status: ", response.status_code)
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Book(BaseModel):
    title: str
    author: str
    isbn: str
    description: str
    price: float
    quantity: int

class OrderCreate(BaseModel):
    isbn: str
    quantity: int

class OrderUpdate(BaseModel):
    status: str


JWKS_CACHE: dict = {"jwks": None}  # CHANGED: added JWKS cache to avoid fetching keys every request


def _get_jwks() -> dict:  # CHANGED: added helper to fetch Supabase JWKS (for ES256)
    if JWKS_CACHE["jwks"] is not None:  # CHANGED: added cache check
        return JWKS_CACHE["jwks"]  # CHANGED: return cached JWKS

    if not SUPABASE_URL:  # CHANGED: added safety check
        raise RuntimeError("SUPABASE_URL is missing")  # CHANGED: added error message

    jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"  # CHANGED: added JWKS URL
    resp = requests.get(jwks_url, timeout=10)  # CHANGED: added JWKS fetch
    resp.raise_for_status()  # CHANGED: added HTTP error handling
    JWKS_CACHE["jwks"] = resp.json()  # CHANGED: store JWKS in cache
    return JWKS_CACHE["jwks"]  # CHANGED: return JWKS


def get_current_user(  # CHANGED: replaced your commented-out function with a working dependency
    request: Request,  # CHANGED: added Request param (was commented out)
    authorization: Optional[str] = Header(None)  # CHANGED: added optional Authorization header (was commented out)
):  # CHANGED: function header line added
    if request.method == "OPTIONS":  # CHANGED: moved this inside the function (it was outside and would break the app)
        return None  # CHANGED: moved inside the function

    if not authorization or not authorization.startswith("Bearer "):  # CHANGED: restored auth header validation
        raise HTTPException(status_code=401, detail="Missing or invalid auth header")  # CHANGED: return 401 (not 422)

    token = authorization.split(" ", 1)[1]  # CHANGED: safer split than split(" ")[1]

    try:
        headers = jwt.get_unverified_header(token)  # CHANGED: added to read alg and kid safely
        alg = headers.get("alg")  # CHANGED: added to branch HS256 vs ES256
        kid = headers.get("kid")  # CHANGED: added to select correct public key

        if alg == "HS256":  # CHANGED: added HS256 fallback to avoid breaking older tokens
            if not SUPABASE_JWT_SECRET:  # CHANGED: added check for HS256 secret
                raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET missing for HS256 verification")  # CHANGED
            payload = jwt.decode(  # CHANGED: added HS256 decode block
                token,  # CHANGED
                SUPABASE_JWT_SECRET,  # CHANGED
                algorithms=["HS256"],  # CHANGED
                audience="authenticated"  # CHANGED
            )  # CHANGED
            return payload  # CHANGED: added return for HS256 path

        jwks = _get_jwks()  # CHANGED: fetch JWKS for ES256 verification
        keys = jwks.get("keys", [])  # CHANGED: read keys list
        key = next((k for k in keys if k.get("kid") == kid), None)  # CHANGED: select matching key by kid
        if not key:  # CHANGED: handle missing kid
            raise HTTPException(status_code=401, detail="Invalid token (unknown kid)")  # CHANGED: specific error

        issuer = f"{SUPABASE_URL}/auth/v1"  # CHANGED: enforce issuer

        payload = jwt.decode(  # CHANGED: ES256 decode using JWKS public key
            token,  # CHANGED
            key,  # CHANGED
            algorithms=["ES256"],  # CHANGED
            audience="authenticated",  # CHANGED
            issuer=issuer  # CHANGED
        )  # CHANGED
        return payload  # CHANGED: return payload for ES256 path

    except HTTPException:  # CHANGED: preserve intentional HTTP errors
        raise  # CHANGED
    except Exception:  # CHANGED: catch-all for invalid tokens
        raise HTTPException(status_code=401, detail="Invalid token")  # CHANGED

#This route is for the page load to get all books
@app.get("/all_books")
def all_books():
    result = supabase.table("books").select("*").order("title").execute()
    return result.data or []

#This route is for the search functionality to find books by title or author
@app.get("/find_books")
def find_books(q: str):
    q = q.strip()
    if not q:
        return []

    result = (
        supabase
        .table("books")
        .select("*")
        .or_(
            f"title.ilike.%{q}%,author.ilike.%{q}%"
        )
        .order("title")
        .execute()
    )
    return result.data or []


@app.get("/find_books")
def find_books(q: str):
    q = q.strip()
    if not q:
        return []

    result = (
        supabase
        .table("books")
        .select("title")
        .ilike("title", f"%{q}%")
        .order("title")
        .execute()
    )
    rows = result.data or []
    return [r.get("title") for r in rows if r.get("title")]


@app.get("/books")
def get_books():
    result = supabase_service.table("books").select("title").execute()  # CHANGED: service_role client + only select title
    rows = result.data or []  # CHANGED: normalize None
    return [r.get("title") for r in rows if r.get("title") is not None]  # CHANGED: return list of titles only

@app.post("/books")
def add_book(book: Book, user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    result = supabase_service.table("books").insert(book.dict()).execute()  # CHANGED: use service_role client (bypasses RLS)
    return result.data[0]

@app.get("/orders")
def get_orders(user=Depends(get_current_user)):
    result = supabase_service.table("orders").select("*").execute()  # CHANGED: use service_role client (bypasses RLS)
    return result.data or []

@app.post("/orders")
def create_order(order: OrderCreate, user=Depends(get_current_user)):
    user_id = user["sub"]

    book_result = (
        supabase_service  # CHANGED: use service_role client
        .table("books")
        .select("*")
        .eq("isbn", order.isbn)
        .single()
        .execute()
    )

    if not book_result.data:
        raise HTTPException(status_code=404, detail="Book not found")

    book = book_result.data

    if order.quantity <= 0:
        raise HTTPException(status_code=400, detail="Invalid quantity")

    if order.quantity > book["quantity"]:
        raise HTTPException(status_code=400, detail="Not enough stock")

    supabase_service.table("books").update({  # CHANGED: use service_role client
        "quantity": book["quantity"] - order.quantity
    }).eq("isbn", order.isbn).execute()

    order_data = {
        "book_isbn": book["isbn"],
        "book_title": book["title"],
        "quantity": order.quantity,
        "status": "pending",
        "customer_id": user_id
    }

    result = supabase_service.table("orders").insert(order_data).execute()  # CHANGED: use service_role client
    return result.data[0]

@app.patch("/orders/{order_id}")
def update_order(order_id: str, order_update: OrderUpdate, user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    result = (
        supabase_service  # CHANGED: use service_role client
        .table("orders")
        .update({"status": order_update.status})
        .eq("id", order_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Order not found")

    return result.data[0]
