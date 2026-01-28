from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware

#FOR TESTING API W/AUTH PUT REQUEST TO UPDATE BOOKS
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials 
from fastapi import Security
from supabase.lib.client_options import ClientOptions

from supabase import create_client
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import os

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

origins = [
    "http://localhost:5500",
    "https://rgereg.github.io"
]

app = FastAPI()
security = HTTPBearer() # for testing api w/auth from docs

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
    print("status:", response.status_code)
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
    description: Optional[str] = ""
    price: float
    quantity: int

class OrderCreate(BaseModel):
    isbn: str
    quantity: int

class OrderUpdate(BaseModel):
    status: str

class UpdateQuantity(BaseModel):
    isbn: str
    quantity: int

class UpdatePrice(BaseModel):
    isbn: str
    price: float

#ADDED AS EXPERIMENT TO FIX BOOKS UPDATE TO DB
class BookUpdate(BaseModel):
    price: float
    quantity: int

#def get_current_user(authorization: Optional[str] = Header(None)):
#    if not authorization or not authorization.startswith("Bearer "):
#        raise HTTPException(status_code=401, detail="Missing or invalid auth header: get current user")
#
#    token = authorization.split(" ")[1]
#    user_resp = supabase.auth.get_user(token)
#    if not user_resp.user:
#        raise HTTPException(status_code=401, detail="Invalid token: get current user")
#
#    return user_resp.user

# Below extracts and validates the JWT from the Authorization header using FastAPI's
# HTTPBearer security scheme. This function verifies the token with Supabase
# and returns the authenticated user object. It handles authentication only;
# authorization (such as role checks) is intentionally enforced at the route level.
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    token = credentials.credentials
    user_resp = supabase.auth.get_user(token)

    if not user_resp.user:
        raise HTTPException(status_code=401, detail="Invalid token")

    return user_resp.user
    
# below creates a Supabase client that includes the current user's JWT in the request headers.
# This is required for Row Level Security (RLS) to work correctly, because Supabase
# evaluates policies (auth.jwt()) based on the JWT attached to the database request.
# Using the global client (anon key only) will cause updates to be silently blocked
# by RLS and return zero rows.
def get_supabase_authed(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    return create_client(
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        options=ClientOptions(headers={"Authorization": f"Bearer {token}"})
    )


# ******************** ROUTES *******************************
@app.get("/books")
def get_books():
    result = supabase.table("books").select("*").order("title", desc=False).execute()
    return result.data or []

@app.post("/books")
def add_book(book: Book, user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")
    result = supabase.table("books").insert(book.dict()).execute()
    return result.data[0]

@app.get("/orders")
def get_orders(user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    user_id = user["sub"]

    query = (
        supabase.table("orders")
        .select("""
            id,
            status,
            customer_id,
            created_at,
            order_items (
                quantity,
                unit_price,
                books (
                    title
                )
            )
        """)
    )

    if role != "employee":
        query = query.eq("customer_id", user_id)

    return query.execute().data or []


@app.post("/orders")
def create_order(order: OrderCreate, user=Depends(get_current_user)):
    user_id = user["sub"]

    book = (
        supabase.table("books")
        .select("*")
        .eq("isbn", order.isbn)
        .single()
        .execute()
        .data
    )

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if order.quantity <= 0:
        raise HTTPException(status_code=400, detail="Invalid quantity")

    if order.quantity > book["quantity"]:
        raise HTTPException(status_code=400, detail="Not enough stock")

    order_row = (
        supabase.table("orders")
        .insert({
            "customer_id": user_id,
            "status": "pending"
        })
        .execute()
        .data[0]
    )

    supabase.table("order_items").insert({
        "order_id": order_row["id"],
        "book_id": book["id"],
        "quantity": order.quantity,
        "unit_price": book["price"]
    }).execute()

    supabase.table("books").update({
        "quantity": book["quantity"] - order.quantity
    }).eq("id", book["id"]).execute()

    return order_row


@app.patch("/orders/{order_id}")
def update_order(order_id: str, order_update: OrderUpdate, user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    result = supabase.table("orders").update({"status": order_update.status}).eq("id", order_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Order not found")
    return result.data[0]

@app.get("/sales/last30days")
def sales_last_30_days(user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()

    result = (
        supabase.table("order_items")
        .select("""
            quantity,
            unit_price,
            created_at
        """)
        .gte("created_at", thirty_days_ago)
        .execute()
    )

    sales = {}
    for item in result.data or []:
        day = item["created_at"][:10]
        sales.setdefault(day, 0)
        sales[day] += item["quantity"] * float(item["unit_price"])

    return {"last_30_days_sales": sales}

@app.post("/update_quantity")
def update_quantity(data: UpdateQuantity, user=Depends(get_current_user)):
    role = user.user_metadata.get("role", "customer")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    result = supabase.table("books").update({"quantity": data.quantity}).eq("isbn", data.isbn).execute()
    return {"status": "success", "data": result.data}

@app.post("/update_price")
def update_price(data: UpdatePrice, user=Depends(get_current_user)):
    role = user.user_metadata.get("role", "customer")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")
    
    result = supabase.table("books").update({"price": data.price}).eq("isbn", data.isbn).execute()
    return {"status": "success", "data": result.data}


# Updates the price and quantity of an existing book identified by ISBN.
# Access is restricted to authenticated users with the 'employee' role.
# The update is executed using a Supabase client that includes the user's JWT
# so that Row Level Security (RLS) policies are evaluated correctly at the
# database layer. A 404 is returned if the ISBN does not exist or the update
# is blocked by policy.
@app.put("/books/{isbn}")
def update_book(
    isbn: str,
    data: BookUpdate,
    user=Depends(get_current_user),
    sb=Depends(get_supabase_authed)
):
    role = user.user_metadata.get("role", "customer")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    result = (
        sb.table("books")
        .update({
            "price": data.price,
            "quantity": data.quantity
        })
        .eq("isbn", isbn)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Book not found")

    return {
        "status": "success",
        "book": result.data[0]
    }


# TEMPORARY DEBUG ROUTE
# uses the same authed client AS ABOVE and does a SELECT by ISBN.
@app.get("/debug/books/{isbn}")
def debug_book_lookup(isbn: str, sb=Depends(get_supabase_authed)):
    res = sb.table("books").select("id,isbn,title,price,quantity").eq("isbn", isbn).execute()
    return {"rows": res.data}
