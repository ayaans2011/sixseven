from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from database import get_db
from security import get_current_user, require_admin, audit_log

router=APIRouter(prefix="/api/coupons",tags=["coupons"])
def now(): return datetime.now(timezone.utc)
def public(c):
 return {"id":str(c["_id"]),"code":c.get("code"),"description":c.get("description",""),"discount_type":c.get("discount_type"),"discount_value":c.get("discount_value"),"max_discount":c.get("max_discount"),"min_order":c.get("min_order",0),"starts_at":c.get("starts_at"),"ends_at":c.get("ends_at"),"usage_limit":c.get("usage_limit"),"used_count":c.get("used_count",0),"customer_ids":c.get("customer_ids",[]),"active":c.get("active",True)}
@router.get("")
async def list_coupons(admin=Depends(require_admin)):
 return [public(c) for c in await get_db().coupons.find({}).sort("created_at",-1).to_list(500)]
@router.post("")
async def create_coupon(d:dict,admin=Depends(require_admin)):
 db=get_db(); code=str(d.get("code") or "").strip().upper(); kind=str(d.get("discount_type") or "PERCENT").upper()
 try:
  value=float(d.get("discount_value")); minimum=float(d.get("min_order") or 0); maximum=None if d.get("max_discount") in (None,"") else float(d["max_discount"]); limit=None if d.get("usage_limit") in (None,"") else int(d["usage_limit"])
 except (TypeError,ValueError): raise HTTPException(400,"Enter valid numeric coupon values")
 if len(code)<3 or len(code)>32 or not code.replace("-","").replace("_","").isalnum(): raise HTTPException(400,"Invalid coupon code")
 if kind not in {"PERCENT","FIXED"} or value<=0 or (kind=="PERCENT" and value>100) or minimum<0 or (maximum is not None and maximum<=0) or (limit is not None and limit<1): raise HTTPException(400,"Invalid discount or usage settings")
 if await db.coupons.find_one({"code":code}): raise HTTPException(409,"Coupon code already exists")
 t=now().isoformat(); doc={"code":code,"description":str(d.get("description") or "")[:240],"discount_type":kind,"discount_value":value,"max_discount":maximum,"min_order":minimum,"starts_at":d.get("starts_at") or None,"ends_at":d.get("ends_at") or None,"usage_limit":limit,"used_count":0,"customer_ids":[str(x) for x in (d.get("customer_ids") or [])][:500],"active":bool(d.get("active",True)),"created_at":t,"updated_at":t,"created_by":admin["email"]}
 r=await db.coupons.insert_one(doc); doc["_id"]=r.inserted_id
 await audit_log("coupon_created",admin["id"],admin["email"],"coupon",str(r.inserted_id),{"code":code}); return public(doc)
@router.put("/{cid}")
async def update_coupon(cid:str,d:dict,admin=Depends(require_admin)):
 db=get_db()
 try: oid=ObjectId(cid)
 except Exception: raise HTTPException(404,"Coupon not found")
 c=await db.coupons.find_one({"_id":oid})
 if not c: raise HTTPException(404,"Coupon not found")
 changes={}
 for k in ("description","starts_at","ends_at","active","customer_ids","usage_limit","max_discount"):
  if k in d: changes[k]=d[k]
 if "description" in changes: changes["description"]=str(changes["description"])[:240]
 if "active" in changes: changes["active"]=bool(changes["active"])
 if "customer_ids" in changes: changes["customer_ids"]=[str(x) for x in changes["customer_ids"]][:500]
 if "usage_limit" in changes and changes["usage_limit"] not in (None,""): changes["usage_limit"]=max(1,int(changes["usage_limit"]))
 if "max_discount" in changes and changes["max_discount"] not in (None,""): changes["max_discount"]=max(.01,float(changes["max_discount"]))
 changes["updated_at"]=now().isoformat(); await db.coupons.update_one({"_id":oid},{"$set":changes})
 await audit_log("coupon_updated",admin["id"],admin["email"],"coupon",cid,{"fields":list(changes)})
 return public(await db.coupons.find_one({"_id":oid}))
@router.delete("/{cid}")
async def delete_coupon(cid:str,admin=Depends(require_admin)):
 db=get_db()
 try: oid=ObjectId(cid)
 except Exception: raise HTTPException(404,"Coupon not found")
 c=await db.coupons.find_one({"_id":oid})
 if not c: raise HTTPException(404,"Coupon not found")
 if await db.orders.find_one({"coupon_id":cid}):
  await db.coupons.update_one({"_id":oid},{"$set":{"active":False,"updated_at":now().isoformat()}}); return {"success":True,"archived":True}
 await db.coupons.delete_one({"_id":oid}); await audit_log("coupon_deleted",admin["id"],admin["email"],"coupon",cid,{"code":c["code"]}); return {"success":True,"archived":False}
@router.post("/apply")
async def apply_coupon(d:dict,user=Depends(get_current_user)):
 if user.get("role")!="customer": raise HTTPException(403,"Customer account required")
 db=get_db(); oid=str(d.get("order_id") or ""); code=str(d.get("code") or "").strip().upper()
 if not code or len(code)>32: raise HTTPException(400,"Enter a valid coupon code")
 try: order=await db.orders.find_one({"_id":ObjectId(oid),"customer_id":user["id"]})
 except Exception: order=None
 if not order: raise HTTPException(404,"Order not found")
 if not order.get("payment_requested") or order.get("payment_status") not in {"UNPAID","PAYMENT_REJECTED"}: raise HTTPException(409,"Coupon cannot be changed after payment has started")
 c=await db.coupons.find_one({"code":code})
 if not c or not c.get("active",True): raise HTTPException(400,"Coupon is invalid or inactive")
 t=now()
 try:
  if c.get("starts_at") and t<datetime.fromisoformat(c["starts_at"].replace("Z","+00:00")): raise HTTPException(400,"Coupon is not active yet")
  if c.get("ends_at") and t>datetime.fromisoformat(c["ends_at"].replace("Z","+00:00")): raise HTTPException(400,"Coupon has expired")
 except ValueError: raise HTTPException(400,"Coupon dates are invalid")
 if c.get("usage_limit") and int(c.get("used_count",0))>=int(c["usage_limit"]): raise HTTPException(400,"Coupon usage limit reached")
 if c.get("customer_ids") and user["id"] not in c["customer_ids"]: raise HTTPException(400,"Coupon is not available for your account")
 base=round(float(order.get("amount",0)),2)
 if base<float(c.get("min_order",0)): raise HTTPException(400,"Order does not meet coupon minimum")
 discount=base*float(c["discount_value"])/100 if c["discount_type"]=="PERCENT" else float(c["discount_value"])
 if c.get("max_discount") is not None: discount=min(discount,float(c["max_discount"]))
 discount=round(min(base,max(0,discount)),2); payable=round(base-discount,2)
 await db.orders.update_one({"_id":order["_id"],"payment_status":{"$in":["UNPAID","PAYMENT_REJECTED"]}},{"$set":{"coupon_id":str(c["_id"]),"coupon_code":code,"discount_amount":discount,"payable_amount":payable,"updated_at":t.isoformat()}})
 await audit_log("coupon_applied",user["id"],user["email"],"order",oid,{"coupon_code":code,"discount_amount":discount})
 return {"success":True,"coupon_code":code,"base_amount":base,"discount_amount":discount,"payable_amount":payable}
