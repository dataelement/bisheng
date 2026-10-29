"""Read-only synthetic business data, exposed through real HTTP and MCP protocols."""
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Path
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP("Bisheng inventory demonstration", stateless_http=True, json_response=True,
              streamable_http_path="/mcp", host="0.0.0.0",
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                  allowed_hosts=["capability-demo:8790", "capability-demo"], allowed_origins=[]))

ORDERS = {
    "DEMO-20261022-001": {"order_id": "DEMO-20261022-001", "customer": "示例客户·华东制造", "product_code": "MAT-001",
                            "product_name": "工业传感器", "quantity": 120, "unit_price": 280, "total": 33600,
                            "currency": "CNY", "delivery_date": "2026-10-28", "status": "待交付"},
    "DEMO-20261022-002": {"order_id": "DEMO-20261022-002", "customer": "示例客户·华南设备", "product_code": "MAT-002",
                            "product_name": "控制模块", "quantity": 40, "unit_price": 650, "total": 26000,
                            "currency": "CNY", "delivery_date": "2026-10-30", "status": "待交付"},
}
INVENTORY = {
    "MAT-001": {"product_code": "MAT-001", "product_name": "工业传感器", "available": 85,
                "incoming": 60, "incoming_date": "2026-10-26", "warehouse": "示例·上海仓"},
    "MAT-002": {"product_code": "MAT-002", "product_name": "控制模块", "available": 120,
                "incoming": 0, "incoming_date": None, "warehouse": "示例·苏州仓"},
}

@mcp.tool()
def demo_check_inventory(product_code: str) -> dict:
    """查询演示库存，返回可用数量、在途数量和到货日期。数据仅用于演示。"""
    record = INVENTORY.get(product_code.upper())
    if record is None:
        raise ValueError("Use demonstration product MAT-001 or MAT-002")
    return {**record, "demo_data": True, "request_id": str(uuid4())}

@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield

app = FastAPI(title="订单查询 · 免配置演示", description="只读合成订单，数据仅用于演示。",
              servers=[{"url": "http://capability-demo:8790"}], lifespan=lifespan)

@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ready"}

@app.get("/orders/{order_id}", operation_id="demo_get_order", description="查询演示订单的客户、物料、数量和交付日期。")
def order(order_id: str = Path(description="演示订单编号，如 DEMO-20261022-001")):
    record = ORDERS.get(order_id.upper())
    if record is None:
        raise HTTPException(404, "Use demonstration order DEMO-20261022-001 or DEMO-20261022-002")
    return {**record, "demo_data": True, "request_id": str(uuid4())}

# Keep protocol handling separate while sharing one internal-only demo process.
app.mount("/", mcp.streamable_http_app())
