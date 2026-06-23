from fastapi import FastAPI

from merlins_collection.routers import auth

app = FastAPI(title="Merlin's Collection API", version="0.1.0")

# Routes are added feature by feature via TDD
app.include_router(auth.router)
