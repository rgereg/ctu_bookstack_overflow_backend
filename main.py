from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware

#FOR TESTING API W/AUTH PUT REQUEST TO UPDATE BOOKS
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials 
from fastapi import Security

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
security = HTTPBearer()  # for testing api w/auth from docs

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
    allow_headers=["Authorization", "Content-Type"],
)


class Book(BaseModel):
    title: str
    author: str
    isbn: str
    description: Optional[str] = ""
    price: float
    quantity: int

class CartAdd(BaseModel):
    isbn: str
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
    sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    sb.postgrest.auth(token)
    return sb


# ******************** ROUTES *******************************
@app.get("/books")
def get_books():
    result = supabase.table("books").select("*").order("title", desc=False).execute()
    return result.data or []

@app.post("/books")
# Putting this function back for now, noticed that render docs showed it being connected to get cart with everything commented out
def add_book(book: Book, user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    try:
        role = user.get("user_metadata", {}).get("role")
        if role != "employee":
            raise HTTPException(status_code=403, detail="Forbidden")
        result = sb.table("books").insert(book.dict()).execute()
        return result.data or []
    except Exception as e:
        print(f"Error in add_book: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Adding a specific get function for carts, requesting them based on the user ID
#@app.get("/cart")
#def get_cart(user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    # Adding another select to identify the cart order_id first.
 #   cartOrder = sb.table("orders").select("*").eq("type", "cart").execute()
 #   result = sb.from_("order_items").select("order_id, quantity, books(title, isbn, price, image_path)").eq("order_id", cartOrder.id).execute()
 #   return result.data or []

@app.get("/cart")
def get_cart(user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    user_id = user["id"]

    cart_res = (
        sb.table("orders")
        .select("id")
        .eq("type", "cart")
        .eq("customer_id", user_id)
        .execute()
    )

    if not cart_res.data:
        return []

    order_id = cart_res.data[0]["id"]

    items = (
        sb.table("order_items")
        .select("book_id, quantity")
        .eq("order_id", order_id)
        .execute()
        .data
    )

    if not items:
        return []

    books_res = (
        sb.table("books")
        .select("id,title,isbn,price,image_path")
        .execute()
    )

    books = {b["id"]: b for b in books_res.data}

    return [
        {
            "quantity": item["quantity"],
            "book": books.get(item["book_id"])
        }
        for item in items
    ]


# Adding items to cart
#@app.post("/cart")
#def add_to_cart(cartData: CartAdd, user = Depends(get_current_user), sb = Depends(get_supabase_authed)):
    # Check if customer already has a cart started
#    cartCheck = sb.table("orders").select("id").eq("type", "cart").execute()

    # If not, create a cart order to begin adding to
#    if not cartCheck:
#        insertData = sb.table("orders").insert({"status": "pending", "type": "cart"}).execute()
#        order_id = insertData.id
#    else:
#        order_id = cartCheck.id
    
    # Find book by isbn and insert book id and amount to the order items table under order id
#    book = sb.table("books").select("id").eq("isbn", cartData.isbn).execute()
#    result = sb.table("order_items").insert({"order_id": order_id, "book_id": book.id, "quantity": cartData.quantity}).execute()
#    return result

@app.post("/cart")
def add_to_cart(cartData: CartAdd, user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    user_id = user["id"]
    cart_res = (
        sb.table("orders")
        .select("id")
        .eq("type", "cart")
        .eq("customer_id", user_id)
        .execute()
    )

    if not cart_res.data:
        created = (
            sb.table("orders")
            .insert({
                "customer_id": user_id,
                "type": "cart",
                "status": "cart"
            })
            .execute()
        )
        order_id = created.data[0]["id"]
    else:
        order_id = cart_res.data[0]["id"]

    book_res = (
        sb.table("books")
        .select("id")
        .eq("isbn", cartData.isbn)
        .execute()
    )

    if not book_res.data:
        raise HTTPException(status_code=404, detail="Book not found")

    book_id = book_res.data[0]["id"]
    sb.table("order_items").insert({
        "order_id": order_id,
        "book_id": book_id,
        "quantity": cartData.quantity
    }).execute()

    return {"status": "added"}



@app.get("/orders")
def get_orders(user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    # Same deal as /cart now, information is filtered through RLS on supabase. Employees should see all while customers only see orders tied to their user_id
    result = sb.table("orders").select("*").execute()
    return result.data or []


@app.post("/orders")
def create_order(order: OrderCreate, user=Depends(get_current_user)):
    user_id = user.id

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
''' THIS COMMENTED OUT SECTION WORKS, BELOW I TRY TO EXPAND IT INTO MEANINGFUL INFORMATION
@app.get("/sales/last30days")
def sales_last_30_days(user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    if not user or not getattr(user, "user_metadata", None):
        raise HTTPException(status_code=401, detail="Not authenticated")

    role = user.user_metadata.get("role", "customer")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()

    result = (
        sb.table("order_items")
        .select("*")
        .gte("created_at", thirty_days_ago)
        .execute()
    )

    return result.data or []
'''
@app.get("/sales/last30days")
def sales_last_30_days(user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    role = user.user_metadata.get("role")
    if role != "employee":
        raise HTTPException(status_code=403)

    items = sb.table("order_items").select("*").execute().data

    books = {b["id"]: b for b in sb.table("books").select("id,title").execute().data}

    orders = {o["id"]: o for o in sb.table("orders").select("id,status,customer_id").execute().data}

    rows = []
    for item in items:
        book = books.get(item["book_id"], {})
        order = orders.get(item["order_id"], {})
        rows.append({
            "created_at": item.get("created_at"),
            "book_title": book.get("title"),
            "quantity": item.get("quantity"),
            "unit_price": item.get("unit_price"),
            "status": order.get("status"),
            "customer_id": order.get("customer_id")
        })

    return rows

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

@app.post("/checkout")
def checkout(user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    cart = (
        sb.table("orders")
        .select("id")
        .eq("type", "cart")
        .eq("customer_id", user.id)
        .maybe_single()
        .execute()
    )

    if not cart.data:
        raise HTTPException(status_code=400, detail="No active cart")

    order_id = cart.data["id"]
    sb.table("orders").update({
        "type": "order",
        "status": "pending"
    }).eq("id", order_id).execute()

    return {"order_id": order_id}

# TEMPORARY DEBUG ROUTES
# uses the same authed client AS ABOVE and does a SELECT by ISBN.
@app.get("/debug/books/{isbn}")
def debug_book_lookup(isbn: str, sb=Depends(get_supabase_authed)):
    res = sb.table("books").select("id,isbn,title,price,quantity").eq("isbn", isbn).execute()
    return {"rows": res.data}

# temporary debug route to expose the update response
@app.put("/debug/books/{isbn}/update")
def debug_update_book(
    isbn: str,
    data: BookUpdate,
    sb=Depends(get_supabase_authed)
):
    # No role check here, this is strictly to see what Supabase returns.
    res = (
        sb.table("books")
        .update({"price": data.price, "quantity": data.quantity})
        .eq("isbn", isbn)
        .execute()
    )
    return {"data": res.data, "count": len(res.data or [])}

# debug route to return the JWT claims as Postgres sees them
@app.get("/debug/jwt")
def debug_jwt(sb=Depends(get_supabase_authed)):
    res = sb.rpc("debug_jwt", {}).execute()
    return {"data": res.data}

