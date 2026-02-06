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
    image_path: Optional[str] = None
    category: Optional[str] = None

    class Config:
        extra = "ignore"


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

class CheckoutInstant(BaseModel):
    book: Book
    quantity: int

class CheckoutPayload(BaseModel):
    order_id: str
    cart_id: str


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
# testing removing options requests from security
def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    if request.method =="OPTIONS":
        return None
        
    token = credentials.credentials
    user_resp = supabase.auth.get_user(token)

    if not user_resp.user:
        raise HTTPException(status_code=401, detail="Invalid token")

    return user_resp.user
    
# below creates a Supabase client that includes the current user's JWT in the request headers.
# This is required for Row Level Security (RLS) to work correctly, because Supabase
# evaluates policies (auth.jwt()) based on the JWT attached to the database request.
# Using the global client (anon key only) will cause updates to be silently blocked
# by RLS and return zero rows. ~n testing removing options requests from security
def get_supabase_authed(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    #token = credentials.credentials
    sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

    if request.method == "OPTIONS":
        return sb

    sb.postgrest.auth(credentials.credentials)
    #sb.postgrest.auth(token)
    return sb


# ******************** ROUTES *******************************
@app.post("/checkout-instant")
def checkout_instant(
    data: CheckoutInstant,
    user=Depends(get_current_user),
    sb=Depends(get_supabase_authed)
):
    
    role = user.user_metadata.get("role")
    if role != "employee":
        raise HTTPException(status_code=403, detail="Forbidden")

    book_resp = sb.table("books").select("*").eq("isbn", data.book.isbn).execute()
    
    # Dropped initial if statement to check if book is in database, should just have the two branches cover if book is present or not   
    if len(book_resp.data) != 0:
        book = book_resp.data[0]
        book_id = book["id"]

        update_resp = sb.table("books").update({
            "price": data.book.price,
            "quantity": book["quantity"] + data.quantity,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", book_id).execute()
        if len(update_resp.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to update book"))
    else:
        insert_resp = sb.table("books").insert({
            "title": data.book.title,
            "author": data.book.author,
            "isbn": data.book.isbn,
            "description": data.book.description,
            "price": data.book.price,
            "quantity": data.quantity,
            "image_path": data.book.image_path,
            "category": data.book.category,
            "is_featured": False
        }).execute()

        if not insert_resp.data:
            raise HTTPException(status_code=500, detail="Failed to create book")

        book_id = insert_resp.data[0]["id"]

    order_resp = sb.table("orders").insert({
        "customer_id": user.id,
        "type": "manufacturer",
        "status": "received"
    }).execute()

    if not order_resp.data:
        raise HTTPException(status_code=500, detail="Failed to create manufacturer order")

    order_id = order_resp.data[0]["id"]

    item_resp = sb.table("order_items").insert({
        "order_id": order_id,
        "book_id": book_id,
        "quantity": data.quantity,
        "unit_price": data.book.price
    }).execute()

    if len(item_resp.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to add items to manufacturer order")
        
    return {
        "status": "manufacturer_order_created",
        "order_id": order_id
    }



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

# get_cart function as it is below works for any customer with or without a cart order in database and now filters correctly if the order type is cart
# Also returns all data from books with book ids in the order items, can be referenced on front end using 'data.books.column'
@app.get("/cart")
def get_cart(user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    # Finds the current row if a cart order is present
    cartOrderRow = sb.table("orders").select("*").eq("customer_id", user.id).eq("type", "cart").execute()

    # Check number of rows returned for cart orders, if no cart or multiple carts present in the table for the current user, return an empty list
    if len(cartOrderRow.data) == 0:
        return []
    elif len(cartOrderRow.data) > 1:
        raise HTTPException(status_code = 400, detail = "More than one cart connected to user")
        return []
    else:
        # Supabase responses .data return a dictionary per row inside of a list, have to reference list index then column to get it from response
        cartOrderId = cartOrderRow.data[0]["id"]
    
    # If the cart is present in the orders table, select all order items and connected books
    items = sb.table("order_items").select("*, books(*)").eq("order_id", cartOrderId).execute()

    # Return resulting rows or empty list if no items are in cart table
    return items.data or []


@app.post("/cart")
def add_to_cart(cartData: CartAdd, user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    # Select row for cart order id
    cartOrderRow = sb.table("orders").select("*").eq("customer_id", user.id).eq("type", "cart").execute()

    # Check number of rows returned, create a cart order if none connected to customer and throw error if multiple are present
    # Assign cartOrderId as order id
    if len(cartOrderRow.data) == 0:
        newOrderRow = sb.table("orders").insert({"customer_id": user.id, "type": "cart", "status": "pending"}).execute()
        cartOrderId = newOrderRow.data[0]["id"]
    elif len(cartOrderRow.data) > 1:
        raise HTTPException(status_code = 400, detail = "More than one cart connected to user")
        return []
    else:
        cartOrderId = cartOrderRow.data[0]["id"]
    
    # Get row for book with matching ISBN and assign id and price to variables
    bookRow = sb.table("books").select("*").eq("isbn", cartData.isbn).execute()
    bookId = bookRow.data[0]["id"]
    bookPrice = bookRow.data[0]["price"]
    bookQuantity = bookRow.data[0]["quantity"]

    # Check if book is already present in order, if it is adjust quantity to add to current order quantity, if not insert row to order items
    checkBook = sb.table("order_items").select("*").eq("book_id", bookId).eq("order_id", cartOrderId).execute()
    if len(checkBook.data) != 0:
        newQuantity = cartData.quantity + checkBook.data[0]["quantity"]
        # Adding a check to see if items in cart are greater than inventory
        if newQuantity > bookQuantity:
            raise HTTPException(status_code = 400, detail = "Number of books in cart greater than inventory")
            return {"status": "Failed to add to cart"}
        
        orderItemId = checkBook.data[0]["id"]
        newRow = sb.table("order_items").update({"quantity": newQuantity}).eq("id", orderItemId).execute()
    else:
        # Check if order quantity greater than inventory again
        if cartData.quantity > bookQuantity:
            raise HTTPException(status_code = 400, detail = "Number of books in cart greater than inventory")
            return {"status": "Failed to add to cart"}
        
        newRow = sb.table("order_items").insert({"order_id": cartOrderId, "book_id": bookId, "quantity": cartData.quantity, "unit_price": bookPrice}).execute()
    
    return {"status": "Book added to cart"}

#cart editing works now, error reference removed
@app.patch("/cart")
def update_cart_item(update: UpdateQuantity, user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    cart_resp = sb.table("orders").select("*").eq("customer_id", user.id).eq("type", "cart").execute()
    if not cart_resp.data:
        raise HTTPException(status_code=400, detail="No active cart")
    cart_id = cart_resp.data[0]["id"]

    bookRow = sb.table("books").select("id, quantity").eq("isbn", update.isbn).execute()
    bookId = bookRow.data[0]["id"]
    # Adding bookQuantity for check
    bookQuantity = bookRow.data[0]["quantity"]
    item_resp = sb.table("order_items").select("*").eq("order_id", cart_id).eq("book_id", bookId).execute()
    if not item_resp.data:
        raise HTTPException(status_code=404, detail="Item not in cart")
    
    item = item_resp.data[0]
    if update.quantity <= 0:
        sb.table("order_items").delete().eq("id", item["id"]).execute()
        return {"status": "removed"}
    # Check if amount in cart is greater than amount in inventory
    elif update.quantity > bookQuantity:
        raise HTTPException(status_code = 400, detail = "Order quantity can't be larger than quantity in stock")
        return {"status": "failed"}
    else:
        sb.table("order_items").update({"quantity": update.quantity}).eq("id", item["id"]).execute()
        return {"status": "updated", "quantity": update.quantity}


@app.delete("/cart/{isbn}")
def remove_cart_item(
    isbn: str,
    user=Depends(get_current_user),
    sb=Depends(get_supabase_authed)
):
    cart_resp = (
        sb.table("orders")
        .select("*")
        .eq("customer_id", user.id)
        .eq("type", "cart")
        .execute()
    )

    if not cart_resp.data:
        raise HTTPException(status_code=400, detail="No active cart")

    cart_id = cart_resp.data[0]["id"]

    book_resp = sb.table("books").select("id").eq("isbn", isbn).execute()
    if not book_resp.data:
        raise HTTPException(status_code=404, detail="Book not found")

    book_id = book_resp.data[0]["id"]

    delete_resp = (
        sb.table("order_items")
        .delete()
        .eq("order_id", cart_id)
        .eq("book_id", book_id)
        .execute()
    )

    if not delete_resp.data:
        raise HTTPException(status_code=404, detail="Item not in cart")

    return {"status": "removed"}

#checkout top placeholder do not remove

@app.post("/checkout/convert-cart")
def convert_cart_to_order(user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    cart_resp = sb.table("orders").select("*").eq("customer_id", user.id).eq("type", "cart").execute()
    if not cart_resp.data:
        raise HTTPException(status_code=404, detail="No active cart found")
    elif len(cart_resp.data) > 1:
        raise HTTPException(status_code=400, detail="Multiple carts found for user")

    cart = cart_resp.data[0]
    cart_id = cart["id"]

    # Going to add a function to remove quantity ordered from book quantity
    cart_items = sb.table("order_items").select("*").eq("order_id", cart_id).execute()
    for item in cart_items.data:
        # Should search every book in the order_items table and update the quantity
        book = sb.table("books").select("quantity").eq("id", item["book_id"]).execute()
        cur_book_quantity = book.data[0]["quantity"]
        new_book_quantity = cur_book_quantity - item["quantity"]
        bookUpdate = sb.table("books").update({"quantity": new_book_quantity}).eq("id", item["book_id"]).execute()

    update_resp = sb.table("orders").update({
        "type": "order",
        "status": "pending",
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", cart_id).execute()

    # Supabase update responses don't return any error data, kept throwing an error on render when I seen it.  Going to change it to test if the response is empty
    # as a method to see if the update failed
    if len(update_resp.data) == 0:
        print(f"[DEBUG] Failed to convert cart {cart_id} to order:", update_resp.error)
        raise HTTPException(status_code=500, detail="Failed to convert cart to order")

    print(f"[DEBUG] Cart {cart_id} converted to order successfully")
    
    return {
        "status": "cart_converted",
        "order_id": cart_id,
        "item_count": len(sb.table("order_items").select("*").eq("order_id", cart_id).execute().data or [])
    }


''' THE BELOW SECTION IS HELD DURING TESTING OF ALTERNATIVE METHOD
@app.post("/checkout/create-order")
def create_order_from_cart(user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    cart_resp = sb.table("orders").select("*").eq("customer_id", user.id).eq("type", "cart").execute()
    if not cart_resp.data or len(cart_resp.data) == 0:
        raise HTTPException(status_code=404, detail="No active cart")
    elif len(cart_resp.data) > 1:
        raise HTTPException(status_code=400, detail="More than one cart connected to user")

    cart = cart_resp.data[0]
    cart_id = cart["id"]

    order_resp = sb.table("orders").insert({
        "customer_id": user.id,
        "type": "order",
        "status": "pending"
    }).execute()

    if not order_resp.data or len(order_resp.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to create order")
    print("NEW ORDER ROW:", order_resp.data) # TODO REMOVE DEBUG
    order_id = order_resp.data[0]["id"]
    print(f"[DEBUG] Created order {order_id} from cart {cart_id}")
    return {"status": "order_created", "order_id": order_id, "cart_id": cart_id}

@app.post("/checkout/add-items")
def add_cart_items_to_order(payload: CheckoutPayload, user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    order_id = payload.order_id
    cart_id = payload.cart_id

    items_resp = sb.table("order_items").select("*").eq("order_id", cart_id).execute()
    if not items_resp.data:
        raise HTTPException(status_code=400, detail="Cart is empty")

    inserted_items = []
    
    for item in items_resp.data:
        insert_resp = sb.table("order_items").insert({
            "order_id": order_id,
            "book_id": item["book_id"],
            "quantity": item["quantity"],
            "unit_price": item["unit_price"]
        }).execute(headers={"Prefer": "return=representation"})
        print("INSERT RESPONSE:", insert_resp) # TODO REMOVE DEBUG
        if insert_resp.error:
            print(f"[DEBUG] Failed to insert item {item['id']}: {insert_resp.error}")
            raise HTTPException(status_code=500, detail=f"Failed to add item {item['id']} to order")

        # TODO REMOVE DEBUG SECTIONS
        inserted_items.extend(insert_resp.data)

    print(f"[DEBUG] Added {len(items_resp.data)} items from cart {cart_id} to order {order_id}")
    return {
        "status": "items_added",
        "order_id": order_id,
        "item_count": len(items_resp.data),
        "inserted_items": inserted_items
    }
    
@app.post("/checkout/clear-cart")
def clear_cart(payload: dict, user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    cart_id = payload.get("cart_id")
    if not cart_id:
        raise HTTPException(status_code=400, detail="Missing cart_id")

    del_items = sb.table("order_items").delete().eq("order_id", cart_id).execute()
    del_cart = sb.table("orders").delete().eq("id", cart_id).execute()

    print(f"[DEBUG] Cleared cart {cart_id}: items_deleted={len(del_items.data) if del_items.data else 0}")
    return {"status": "cart_cleared", "cart_id": cart_id}
'''
#checkout bottom placeholder do not remove

@app.get("/orders")
def get_orders(user=Depends(get_current_user), sb=Depends(get_supabase_authed)):
    # Same deal as /cart now, information is filtered through RLS on supabase. Employees should see all while customers only see orders tied to their user_id
    # The orders table doesn't have a foreign key connected to the books table, can't call titles of books from orders. Gonna keep it simple unless we really need it
    result = sb.table("orders").select("*, order_items(*)").neq("type", "cart").execute()
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

