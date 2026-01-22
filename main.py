from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt, JWTError
from supabase import create_client
from pydantic import BaseModel
import os

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

ALGORITHM = "HS256"

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

origins = [
    "http://localhost:5500",
    "https://rgereg.github.io"
]

app = FastAPI()

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

def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")

    token = authorization.split(" ")[1]

    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=[ALGORITHM],
            audience="authenticated"
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    return payload

@app.get("/books")
def get_books(user=Depends(get_current_user)):
    result = supabase.table("books").select("*").execute()
    books = result.data
    if books is None:
        books = []
    return books

@app.post("/books")
def add_book(book: Book, user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Only employees can add books")
    result = supabase.table("books").insert(book.dict()).execute()
    return result.data[0]

@app.get("/orders")
def get_orders(user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    user_id = user.get("sub")

    result = supabase.table("orders").select("*").execute()
    orders = result.data
    if orders is None:
        orders = []

    if role == "customer":
        orders = [o for o in orders if o.get("customer_id") == user_id]

    return orders

@app.post("/orders")
def create_order(order: OrderCreate, user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    if role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can place orders")

    book_result = supabase.table("books").select("*").eq("isbn", order.isbn).execute()
    if not book_result.data:
        raise HTTPException(status_code=404, detail="Book not found")

    book = book_result.data[0]
    if order.quantity > book["quantity"]:
        raise HTTPException(status_code=400, detail="Not enough stock available")

    supabase.table("books").update({"quantity": book["quantity"] - order.quantity}).eq("isbn", order.isbn).execute()

    order_data = {
        "book_isbn": book["isbn"],
        "book_title": book["title"],
        "quantity": order.quantity,
        "status": "pending",
        "customer_id": user.get("sub")
    }

    result = supabase.table("orders").insert(order_data).execute()
    return result.data[0]

@app.patch("/orders/{order_id}")
def update_order(order_id: str, order_update: OrderUpdate, user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Only employees can update orders")

    result = supabase.table("orders").update({"status": order_update.status}).eq("id", order_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Order not found")

    return result.data[0]
