"""FastAPI app entrypoint for jbuild."""

from fastapi import FastAPI

from .traits import router as traits_router


app = FastAPI(title="jbuild API", version="0.1.0")
app.include_router(traits_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "jbuild"}
