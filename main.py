from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt, JWTError
from supabase import create_client
from pydantic import BaseModel
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
ALGORITHM = "HS256"


def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401)

    token = authorization.split(" ")[1]

    try:
        return jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=[ALGORITHM],
            audience="authenticated"
        )
    except JWTError:
        raise HTTPException(status_code=401)


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


class PromoteRequest(BaseModel):
    email: str


@app.post("/admin/promote")
def promote_user(req: PromoteRequest, user=Depends(get_current_user)):
    if user.get("user_metadata", {}).get("role") != "employee":
        raise HTTPException(status_code=403)

    supabase.auth.admin.update_user_by_email(
        req.email,
        {"user_metadata": {"role": "employee"}}
    )

    return {"status": "promoted"}


@app.get("/books")
def get_books(user=Depends(get_current_user)):
    return supabase.table("books").select("*").execute().data


@app.post("/books")
def add_book(book: Book, user=Depends(get_current_user)):
    if user.get("user_metadata", {}).get("role") != "employee":
        raise HTTPException(status_code=403)

    return supabase.table("books").insert(book.dict()).execute().data[0]


@app.get("/orders")
def get_orders(user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")
    email = user.get("email")

    orders = supabase.table("orders").select("*").execute().data
    if role == "customer":
        orders = [o for o in orders if o["customer_email"] == email]

    return orders


@app.post("/orders")
def create_order(order: OrderCreate, user=Depends(get_current_user)):
    if user.get("user_metadata", {}).get("role") != "customer":
        raise HTTPException(status_code=403)

    book = supabase.table("books").select("*").eq("isbn", order.isbn).execute().data
    if not book:
        raise HTTPException(status_code=404)

    book = book[0]
    if order.quantity > book["quantity"]:
        raise HTTPException(status_code=400)

    supabase.table("books").update({
        "quantity": book["quantity"] - order.quantity
    }).eq("isbn", order.isbn).execute()

    return supabase.table("orders").insert({
        "book_isbn": book["isbn"],
        "book_title": book["title"],
        "quantity": order.quantity,
        "status": "pending",
        "customer_email": user["email"]
    }).execute().data[0]


@app.patch("/orders/{order_id}")
def update_order(order_id: str, update: OrderUpdate, user=Depends(get_current_user)):
    if user.get("user_metadata", {}).get("role") != "employee":
        raise HTTPException(status_code=403)

    result = supabase.table("orders").update({
        "status": update.status
    }).eq("id", order_id).execute()

    if not result.data:
        raise HTTPException(status_code=404)

    return result.data[0]
