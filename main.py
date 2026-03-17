from api import app
```

→ **Commit changes**

**2 →** Render → `ticketradar-api` → **Settings → Start Command** → remplace par :
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```
→ **Save**

**3 →** Render → **Manual Deploy → Clear build cache & deploy**

**4 →** Quand c'est Live → teste :
```
https://ticketradar-api.onrender.com
