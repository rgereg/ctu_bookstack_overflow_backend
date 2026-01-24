from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from pydantic import BaseModel
from jose import jwt
from typing import Optional
import os


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

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


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None)
):

    if request.method == "OPTIONS":
        return None

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid auth header")

    token = authorization.split(" ")[1]

    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated"
        )
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/books")
def get_books():
    result = supabase.table("books").select("*").execute()
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
    result = supabase.table("orders").select("*").execute()
    return result.data or []

@app.post("/orders")
def create_order(order: OrderCreate, user=Depends(get_current_user)):
    user_id = user["sub"]

    book_result = (
        supabase
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

    supabase.table("books").update({
        "quantity": book["quantity"] - order.quantity
    }).eq("isbn", order.isbn).execute()

    order_data = {
        "book_isbn": book["isbn"],
        "book_title": book["title"],
        "quantity": order.quantity,
        "status": "pending",
        "customer_id": user_id
    }

    result = supabase.table("orders").insert(order_data).execute()
    return result.data[0]

@app.patch("/orders/{order_id}")
def update_order(order_id: str, order_update: OrderUpdate, user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    result = (
        supabase
        .table("orders")
        .update({"status": order_update.status})
        .eq("id", order_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Order not found")

    return result.data[0]
