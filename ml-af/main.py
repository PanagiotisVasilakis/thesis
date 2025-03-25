from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "ML Service is up and running!"}