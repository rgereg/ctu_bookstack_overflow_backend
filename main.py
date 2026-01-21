from fastapi import FastAPI, Depends, HTTPException, Header
from jose import jwt, JWTError
from supabase import create_client
import os

app = FastAPI()

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
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=[ALGORITHM],
            audience="authenticated"
        )
        return payload
    except JWTError:
        raise HTTPException(status_code=401)


@app.get("/books")
def get_books(user=Depends(get_current_user)):
    result = supabase.table("books").select("*").execute()
    return result.data


@app.post("/books")
def add_book(book: dict, user=Depends(get_current_user)):
    role = user.get("user_metadata", {}).get("role")

    if role != "admin":
        raise HTTPException(status_code=403)

    result = supabase.table("books").insert(book).execute()
    return result.data[0]
