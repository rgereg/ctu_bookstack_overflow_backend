from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
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

def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid auth header: get current user")

    token = authorization.split(" ")[1]
    user_resp = supabase.auth.get_user(token)
    if not user_resp.user:
        raise HTTPException(status_code=401, detail="Invalid token: get current user")

    return user_resp.user

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
    result3 = supabase.table("books").select("isbn").eq("isbn", data.isbn).execute() # DEBUG SECTION TODO REMOVE
    result2 = supabase.table("books").update({"quantity": data.quantity}).eq("isbn", data.isbn).execute()  # DEBUG SECTION TODO REMOVE
    result = supabase.table("books").update({"quantity": data.quantity}).eq("isbn", data.isbn).execute()
    return {"status": "success", "data": result.data "data2": result2.data "data3": result3.data}

@app.post("/update_price")
def update_price(data: UpdatePrice, user=Depends(get_current_user)):
    role = user.user_metadata.get("role", "customer")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")
    
    result = supabase.table("books").update({"price": data.price}).eq("isbn", data.isbn).execute()
    return {"status": "success", "data": result.data}

