from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
import uuid

from supabase import create_client, Client

const SUPABASE_URL = "https://ajvplpbxsrxgdldcosdf.supabase.co";
const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFqdnBscGJ4c3J4Z2RsZGNvc2RmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njg3NjQ0ODksImV4cCI6MjA4NDM0MDQ4OX0.Uw5xQLK2TSYeEVDzTYW0jwwui_1CMS_pfPpl4h5_bLk";


supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

app = FastAPI()

#CORS stuff
origins = [
    "http://localhost:5500",
    "https://rgereg.github.io"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#pydantic models
class BookItem(BaseModel):
    book_id: str
    quantity: int
    unit_price: float

class CheckoutPayload(BaseModel):
    items: List[BookItem]

class UpdatePricePayload(BaseModel):
    isbn: str
    price: float

class UpdateQuantityPayload(BaseModel):
    isbn: str
    quantity: int

#authorization stuff
def get_jwt(request: Request) -> str:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")
    return auth_header.split(" ")[1]

def get_user(token: str):
    user_res = supabase.auth.get_user(token)
    if user_res.user is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user_res.user


#load
@app.get("/books")
async def get_books():
    res = supabase.table("books").select("*").execute()
    if res.error:
        raise HTTPException(status_code=500, detail=res.error.message)
    return res.data

#checkout stuff
@app.post("/checkout")
async def checkout(payload: CheckoutPayload, request: Request):
    token = get_jwt(request)
    user = get_user(token)
    customer_id = user.id

    book_ids = [item.book_id for item in payload.items]
    stock_res = supabase.table("books").select("id, quantity, price").in_("id", book_ids).execute()
    if stock_res.error:
        raise HTTPException(status_code=500, detail=stock_res.error.message)

    stock_map = {b["id"]: b for b in stock_res.data}

    for item in payload.items:
        if item.book_id not in stock_map:
            raise HTTPException(status_code=400, detail=f"Book {item.book_id} not found")
        if stock_map[item.book_id]["quantity"] < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough stock for book {item.book_id}"
            )

    # Create order
    order_number_res = supabase.table("orders").select("order_number").order("order_number", desc=True).limit(1).execute()
    if order_number_res.error:
        raise HTTPException(status_code=500, detail=order_number_res.error.message)
    next_order_number = 1
    if order_number_res.data:
        next_order_number = order_number_res.data[0]["order_number"] + 1

    order_res = supabase.table("orders").insert({
        "customer_id": customer_id,
        "status": "pending",
        "type": "online",
        "order_number": next_order_number,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }).execute()

    if order_res.error:
        raise HTTPException(status_code=500, detail=order_res.error.message)

    order_id = order_res.data[0]["id"]

    order_items_payload = []
    for item in payload.items:
        order_items_payload.append({
            "order_id": order_id,
            "book_id": item.book_id,
            "quantity": item.quantity,
            "unit_price": float(stock_map[item.book_id]["price"]),
            "created_at": datetime.utcnow()
        })

    items_res = supabase.table("order_items").insert(order_items_payload).execute()
    if items_res.error:
        raise HTTPException(status_code=500, detail=items_res.error.message)

    for item in payload.items:
        new_qty = stock_map[item.book_id]["quantity"] - item.quantity
        update_res = supabase.table("books").update({
            "quantity": new_qty,
            "updated_at": datetime.utcnow()
        }).eq("id", item.book_id).execute()
        if update_res.error:
            raise HTTPException(status_code=500, detail=update_res.error.message)

    return {"message": "Order placed successfully", "order_id": order_id}


@app.post("/update_price")
async def update_price(payload: UpdatePricePayload, request: Request):
    token = get_jwt(request)
    user = get_user(token)
    if user.user_metadata.get("role") != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    res = supabase.table("books").update({
        "price": Decimal(str(payload.price)),
        "updated_at": datetime.utcnow()
    }).eq("isbn", payload.isbn).execute()
    if res.error:
        raise HTTPException(status_code=500, detail=res.error.message)
    return {"message": "Price updated"}


@app.post("/update_quantity")
async def update_quantity(payload: UpdateQuantityPayload, request: Request):
    token = get_jwt(request)
    user = get_user(token)
    if user.user_metadata.get("role") != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    res = supabase.table("books").update({
        "quantity": payload.quantity,
        "updated_at": datetime.utcnow()
    }).eq("isbn", payload.isbn).execute()
    if res.error:
        raise HTTPException(status_code=500, detail=res.error.message)
    return {"message": "Quantity updated"}

#order stuff
@app.get("/orders")
async def get_orders(customer_id: Optional[str] = None, request: Request = None):
    token = get_jwt(request)
    user = get_user(token)
    role = user.user_metadata.get("role")

    query = supabase.table("orders").select(
        """
        id,
        order_number,
        customer_id,
        status,
        created_at,
        order_items (
            quantity,
            unit_price,
            book_id,
            books (
                title
            )
        )
        """
    )

    if customer_id:
        if user.id != customer_id and role != "employee":
            raise HTTPException(status_code=403, detail="Forbidden")
        query = query.eq("customer_id", customer_id)
    else:
        if role != "employee":
            raise HTTPException(status_code=403, detail="Forbidden")

    res = query.execute()

    if res.error:
        raise HTTPException(status_code=500, detail=res.error.message)

    return res.data

@app.get("/order_items")
async def get_order_items(order_id: str, request: Request):
    token = get_jwt(request)
    user = get_user(token)
    role = user.user_metadata.get("role")

    # employee can access all
    if role == "employee":
        res = supabase.table("order_items").select("*").eq("order_id", order_id).execute()
        if res.error:
            raise HTTPException(status_code=500, detail=res.error.message)
        return res.data

    # customer can access only own order
    order_res = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not order_res.data or order_res.data[0]["customer_id"] != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    res = supabase.table("order_items").select("*").eq("order_id", order_id).execute()
    if res.error:
        raise HTTPException(status_code=500, detail=res.error.message)
    return res.data
