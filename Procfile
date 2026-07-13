# Alternative zum Dockerfile für Buildpack-/Nixpacks-Deploys (z. B. Railway ohne Docker).
# Bei vorhandenem Dockerfile nutzt die Plattung i. d. R. das Dockerfile und ignoriert dies.
web: uvicorn estimateiq.api.main:app --host 0.0.0.0 --port $PORT
