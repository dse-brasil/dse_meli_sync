import logging
from fastapi import APIRouter, Depends, status, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.db.models import WebhookEvent, Product, Conversation
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# API Endpoints to feed the dashboard

@router.get("/stats", status_code=status.HTTP_200_OK)
async def get_admin_stats(db: AsyncSession = Depends(get_db)):
    """
    Returns aggregated stats for the admin dashboard.
    """
    try:
        # 1. Count WebhookEvents by status
        status_stmt = select(WebhookEvent.status, func.count(WebhookEvent.id)).group_by(WebhookEvent.status)
        status_res = await db.execute(status_stmt)
        status_counts = dict(status_res.all())

        # 2. Count total Products
        prod_stmt = select(func.count(Product.id))
        prod_res = await db.execute(prod_stmt)
        total_products = prod_res.scalar() or 0

        # 3. Count total Conversations
        conv_stmt = select(func.count(Conversation.id))
        conv_res = await db.execute(conv_stmt)
        total_conversations = conv_res.scalar() or 0

        # Meli Integration Status
        meli_auth = settings.MELI_CLIENT_SECRET is not None and settings.MELI_CLIENT_SECRET != "your-meli-client-secret"

        return {
            "total_webhooks": sum(status_counts.values()),
            "webhook_status": {
                "received": status_counts.get("received", 0),
                "processing": status_counts.get("processing", 0),
                "processed": status_counts.get("processed", 0),
                "failed": status_counts.get("failed", 0)
            },
            "total_products": total_products,
            "total_conversations": total_conversations,
            "meli_authenticated": meli_auth,
            "llm_provider": settings.LLM_PROVIDER
        }
    except Exception as e:
        logger.error(f"Failed to fetch admin stats: {str(e)}")
        return {"error": str(e)}


@router.get("/webhooks", status_code=status.HTTP_200_OK)
async def get_admin_webhooks(db: AsyncSession = Depends(get_db)):
    """
    Returns latest 50 webhook events.
    """
    try:
        stmt = select(WebhookEvent).order_by(WebhookEvent.created_at.desc()).limit(50)
        res = await db.execute(stmt)
        events = res.scalars().all()
        return [
            {
                "id": str(e.id),
                "topic": e.topic,
                "resource": e.resource,
                "status": e.status,
                "error_message": e.error_message,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "processed_at": e.processed_at.isoformat() if e.processed_at else None
            }
            for e in events
        ]
    except Exception as e:
        logger.error(f"Failed to fetch admin webhooks: {str(e)}")
        return {"error": str(e)}


@router.get("/products", status_code=status.HTTP_200_OK)
async def get_admin_products(db: AsyncSession = Depends(get_db)):
    """
    Returns latest 50 synced products.
    """
    try:
        stmt = select(Product).order_by(Product.updated_at.desc()).limit(50)
        res = await db.execute(stmt)
        products = res.scalars().all()
        return [
            {
                "id": p.id,
                "title": p.title,
                "price": p.price,
                "permalink": p.permalink,
                "status": p.status,
                "stock": p.stock,
                "attributes": p.attributes,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None
            }
            for p in products
        ]
    except Exception as e:
        logger.error(f"Failed to fetch admin products: {str(e)}")
        return {"error": str(e)}

class ProductSyncRequest(BaseModel):
    item_id: str

@router.post("/products", status_code=status.HTTP_201_CREATED)
async def sync_or_add_product(
    payload: ProductSyncRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Manually syncs or adds a product from Mercado Livre catalog to local database.
    """
    item_id = payload.item_id.strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="Item ID cannot be empty.")
    
    try:
        from app.services.meli_client import meli_client
        product_data = await meli_client.get_item_details(item_id)
        
        stmt = select(Product).where(Product.id == item_id)
        res = await db.execute(stmt)
        db_product = res.scalar_one_or_none()
        
        if not db_product:
            db_product = Product(
                id=item_id,
                title=product_data["title"],
                price=product_data["price"],
                permalink=product_data.get("permalink"),
                status=product_data["status"],
                stock=product_data.get("available_quantity", 0),
                attributes=product_data.get("attributes", {})
            )
            db.add(db_product)
        else:
            db_product.title = product_data["title"]
            db_product.price = product_data["price"]
            db_product.permalink = product_data.get("permalink")
            db_product.status = product_data["status"]
            db_product.stock = product_data.get("available_quantity", 0)
            db_product.attributes = product_data.get("attributes", {})
            
        await db.commit()
        await db.refresh(db_product)
        
        return {
            "message": "Produto sincronizado com sucesso!",
            "product": {
                "id": db_product.id,
                "title": db_product.title,
                "price": db_product.price,
                "status": db_product.status,
                "stock": db_product.stock
            }
        }
    except Exception as e:
        logger.error(f"Failed manual product sync for {item_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro de sincronizacao: {str(e)}")


@router.get("/alerts", status_code=status.HTTP_200_OK)
async def get_admin_alerts(db: AsyncSession = Depends(get_db)):
    """
    Returns all webhook events failed due to prompt injection or security exceptions.
    """
    try:
        stmt = (
            select(WebhookEvent)
            .where(
                (WebhookEvent.status == "failed") & 
                (
                    (WebhookEvent.error_message.like("%injection%")) |
                    (WebhookEvent.error_message.like("%Guardrail%")) |
                    (WebhookEvent.error_message.like("%Invalid signature%"))
                )
            )
            .order_by(WebhookEvent.created_at.desc())
            .limit(50)
        )
        res = await db.execute(stmt)
        events = res.scalars().all()
        return [
            {
                "id": str(e.id),
                "topic": e.topic,
                "resource": e.resource,
                "error_message": e.error_message,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None
            }
            for e in events
        ]
    except Exception as e:
        logger.error(f"Failed to fetch security alerts: {str(e)}")
        return {"error": str(e)}


# Server view for dashboard UI

@router.get("", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """
    Serves the beautiful, premium Single Page Admin Dashboard.
    """
    html_content = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DSE Meli Sync - Painel Administrativo</title>
    
    <!-- Google Fonts Inter & Outfit -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    
    <!-- FontAwesome for Premium Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">

    <style>
        :root {
            --bg-primary: #090d16;
            --bg-secondary: #111827;
            --bg-glass: rgba(17, 24, 39, 0.75);
            --border-glass: rgba(255, 255, 255, 0.08);
            --accent-primary: #8b5cf6; /* Violet */
            --accent-secondary: #06b6d4; /* Cyan */
            --accent-primary-glow: rgba(139, 92, 246, 0.4);
            --accent-secondary-glow: rgba(6, 182, 212, 0.4);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            
            --success: #10b981;
            --danger: #f43f5e;
            --warning: #f59e0b;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Outfit', 'Inter', sans-serif;
            scrollbar-width: thin;
            scrollbar-color: rgba(255,255,255,0.1) transparent;
        }

        body {
            background-color: var(--bg-primary);
            color: var(--text-primary);
            overflow: hidden;
            height: 100vh;
            display: flex;
        }

        /* Ambient background glows */
        .ambient-glow-1 {
            position: absolute;
            top: -200px;
            left: -200px;
            width: 600px;
            height: 600px;
            border-radius: 50%;
            background: radial-gradient(circle, var(--accent-primary-glow) 0%, transparent 70%);
            z-index: 1;
            pointer-events: none;
            filter: blur(100px);
        }

        .ambient-glow-2 {
            position: absolute;
            bottom: -200px;
            right: -200px;
            width: 600px;
            height: 600px;
            border-radius: 50%;
            background: radial-gradient(circle, var(--accent-secondary-glow) 0%, transparent 70%);
            z-index: 1;
            pointer-events: none;
            filter: blur(100px);
        }

        /* Layout Structure */
        .sidebar {
            width: 280px;
            background-color: var(--bg-secondary);
            border-right: 1px solid var(--border-glass);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            padding: 24px;
            z-index: 10;
        }

        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            z-index: 10;
        }

        /* Sidebar Logo */
        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 40px;
        }

        .brand-logo {
            width: 42px;
            height: 42px;
            background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 15px var(--accent-primary-glow);
        }

        .brand-logo i {
            color: white;
            font-size: 20px;
        }

        .brand-title {
            font-size: 20px;
            font-weight: 700;
            letter-spacing: 0.5px;
            background: linear-gradient(to right, #ffffff, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        /* Sidebar Menu */
        .menu-list {
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 6px;
            flex: 1;
        }

        .menu-item {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 12px 18px;
            border-radius: 12px;
            cursor: pointer;
            color: var(--text-secondary);
            font-weight: 500;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            border: 1px solid transparent;
        }

        .menu-item:hover {
            color: white;
            background: rgba(255, 255, 255, 0.03);
            border-color: rgba(255, 255, 255, 0.05);
        }

        .menu-item.active {
            color: white;
            background: linear-gradient(90deg, rgba(139, 92, 246, 0.15) 0%, rgba(6, 182, 212, 0.05) 100%);
            border-color: rgba(139, 92, 246, 0.3);
            box-shadow: inset 0 0 10px rgba(139, 92, 246, 0.1);
        }

        .menu-item i {
            font-size: 18px;
            width: 20px;
            text-align: center;
            transition: transform 0.3s;
        }

        .menu-item.active i {
            color: var(--accent-secondary);
            transform: scale(1.15);
        }

        /* Sidebar Footer */
        .sidebar-footer {
            border-top: 1px solid var(--border-glass);
            padding-top: 20px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .system-status {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 13px;
            color: var(--text-secondary);
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 6px;
            font-weight: 600;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--success);
            box-shadow: 0 0 10px var(--success);
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.3); opacity: 0.5; }
            100% { transform: scale(1); opacity: 1; }
        }

        /* Top Header */
        .header {
            height: 80px;
            padding: 0 40px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border-glass);
            background-color: rgba(9, 13, 22, 0.4);
            backdrop-filter: blur(10px);
        }

        .header-title {
            font-size: 22px;
            font-weight: 700;
        }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .btn {
            background: var(--bg-glass);
            border: 1px solid var(--border-glass);
            color: white;
            padding: 10px 18px;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s;
        }

        .btn:hover {
            border-color: var(--accent-primary);
            box-shadow: 0 0 12px rgba(139, 92, 246, 0.2);
            transform: translateY(-1px);
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
            border: none;
        }

        .btn-primary:hover {
            box-shadow: 0 0 18px var(--accent-primary-glow);
        }

        .btn-danger {
            background: rgba(244, 63, 94, 0.1);
            border-color: rgba(244, 63, 94, 0.3);
            color: var(--danger);
        }
        .btn-danger:hover {
            background: rgba(244, 63, 94, 0.2);
            border-color: var(--danger);
            box-shadow: 0 0 12px rgba(244, 63, 94, 0.2);
        }

        /* Main Workspace Content */
        .workspace {
            flex: 1;
            padding: 40px;
            overflow-y: auto;
            position: relative;
        }

        .view-panel {
            display: none;
            animation: fadeIn 0.4s ease-out forwards;
        }

        .view-panel.active {
            display: block;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Grid layouts */
        .grid-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .stat-card {
            background: var(--bg-glass);
            border: 1px solid var(--border-glass);
            border-radius: 16px;
            padding: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            backdrop-filter: blur(10px);
            transition: all 0.3s;
        }

        .stat-card:hover {
            border-color: rgba(255, 255, 255, 0.15);
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            transform: translateY(-3px);
        }

        .stat-value {
            font-size: 28px;
            font-weight: 800;
            background: linear-gradient(to right, #ffffff, #e9d5ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-top: 4px;
        }

        .stat-label {
            font-size: 13px;
            color: var(--text-secondary);
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .stat-icon {
            width: 50px;
            height: 50px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
        }

        .stat-icon.purple { background: rgba(139, 92, 246, 0.15); color: var(--accent-primary); border: 1px solid rgba(139, 92, 246, 0.3); }
        .stat-icon.cyan { background: rgba(6, 182, 212, 0.15); color: var(--accent-secondary); border: 1px solid rgba(6, 182, 212, 0.3); }
        .stat-icon.green { background: rgba(16, 185, 129, 0.15); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.3); }
        .stat-icon.red { background: rgba(244, 63, 94, 0.15); color: var(--danger); border: 1px solid rgba(244, 63, 94, 0.3); }
        .stat-icon.yellow { background: rgba(245, 158, 11, 0.15); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.3); }

        /* Progress Bar for Goal progress */
        .progress-wrapper {
            margin-top: 12px;
            width: 100%;
        }
        .progress-bar-bg {
            width: 100%;
            height: 10px;
            background: rgba(255,255,255,0.05);
            border-radius: 6px;
            overflow: hidden;
            border: 1px solid var(--border-glass);
        }
        .progress-bar-fill {
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
            border-radius: 6px;
            box-shadow: 0 0 8px var(--accent-primary-glow);
            transition: width 1s ease-out;
        }

        /* Glass Cards Layout */
        .glass-card {
            background: var(--bg-glass);
            border: 1px solid var(--border-glass);
            border-radius: 20px;
            padding: 24px;
            backdrop-filter: blur(10px);
            margin-bottom: 24px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }

        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 20px;
        }

        .card-title {
            font-size: 18px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .card-title i {
            color: var(--accent-secondary);
        }

        /* Forms Styling */
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .form-group label {
            font-size: 12px;
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
        }

        .form-input, select.form-input {
            width: 100%;
            background: #05070d;
            border: 1px solid var(--border-glass);
            color: white;
            padding: 12px 16px;
            border-radius: 10px;
            font-size: 14px;
            outline: none;
            transition: all 0.3s;
        }

        .form-input:focus {
            border-color: var(--accent-primary);
            box-shadow: 0 0 8px var(--accent-primary-glow);
        }

        /* Tables */
        .table-container {
            width: 100%;
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }

        th {
            padding: 14px 18px;
            font-size: 12px;
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid var(--border-glass);
        }

        td {
            padding: 16px 18px;
            font-size: 14px;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            color: var(--text-primary);
        }

        tr:hover td {
            background-color: rgba(255,255,255,0.02);
        }

        .badge {
            display: inline-flex;
            align-items: center;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            gap: 6px;
        }

        .badge-success { background: rgba(16, 185, 129, 0.12); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.3); }
        .badge-danger { background: rgba(244, 63, 94, 0.12); color: var(--danger); border: 1px solid rgba(244, 63, 94, 0.3); }
        .badge-warning { background: rgba(245, 158, 11, 0.12); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.3); }
        .badge-info { background: rgba(6, 182, 212, 0.12); color: var(--accent-secondary); border: 1px solid rgba(6, 182, 212, 0.3); }

        /* Modals */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.85);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(8px);
        }

        .modal-content {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-glass);
            border-radius: 20px;
            width: 80%;
            max-width: 800px;
            max-height: 80vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            box-shadow: 0 20px 60px rgba(0,0,0,0.8);
            animation: modalSlide 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        @keyframes modalSlide {
            from { transform: translateY(30px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        .modal-header {
            padding: 20px 30px;
            border-bottom: 1px solid var(--border-glass);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .modal-body {
            padding: 30px;
            overflow-y: auto;
            background-color: #05070d;
        }

        .json-viewer {
            font-family: 'Courier New', Courier, monospace;
            font-size: 13px;
            color: #10b981;
            white-space: pre-wrap;
            word-wrap: break-word;
        }

        /* AI Simulator Chat Pane */
        .chat-container {
            display: grid;
            grid-template-columns: 320px 1fr;
            gap: 24px;
            height: calc(100vh - 200px);
        }

        .chat-config {
            background: rgba(255,255,255,0.02);
            border: 1px solid var(--border-glass);
            border-radius: 20px;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        .config-group {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .config-label {
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
            font-weight: 600;
        }

        .config-value {
            background: #05070d;
            border: 1px solid var(--border-glass);
            border-radius: 10px;
            padding: 12px;
            font-size: 13px;
            color: var(--text-primary);
        }

        .chat-workspace {
            background: var(--bg-glass);
            border: 1px solid var(--border-glass);
            border-radius: 20px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            overflow: hidden;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }

        .chat-messages {
            flex: 1;
            padding: 30px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 20px;
            background: rgba(5, 7, 13, 0.4);
        }

        .msg {
            max-width: 75%;
            display: flex;
            flex-direction: column;
            gap: 6px;
            animation: chatSlide 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        @keyframes chatSlide {
            from { transform: translateY(15px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        .msg.buyer { align-self: flex-start; }
        .msg.agent { align-self: flex-end; }

        .msg-bubble {
            padding: 16px 20px;
            border-radius: 18px;
            font-size: 14px;
            line-height: 1.6;
        }

        .msg.buyer .msg-bubble {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-glass);
            border-bottom-left-radius: 4px;
            color: white;
        }

        .msg.agent .msg-bubble {
            background: linear-gradient(135deg, var(--accent-primary) 0%, rgba(139, 92, 246, 0.6) 100%);
            border-bottom-right-radius: 4px;
            color: white;
            box-shadow: 0 4px 15px rgba(139, 92, 246, 0.2);
        }

        .msg-meta {
            font-size: 11px;
            color: var(--text-secondary);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .msg.buyer .msg-meta { justify-content: flex-start; }
        .msg.agent .msg-meta { justify-content: flex-end; }

        .chat-input-area {
            padding: 24px;
            border-top: 1px solid var(--border-glass);
            display: flex;
            gap: 16px;
            align-items: center;
            background: var(--bg-secondary);
        }

        .chat-input {
            flex: 1;
            background: #05070d;
            border: 1px solid var(--border-glass);
            color: white;
            padding: 16px 24px;
            border-radius: 12px;
            font-size: 14px;
            outline: none;
            transition: all 0.3s;
        }

        .chat-input:focus {
            border-color: var(--accent-secondary);
            box-shadow: 0 0 10px rgba(6, 182, 212, 0.15);
        }

        .security-scan-indicator {
            font-size: 12px;
            color: var(--success);
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 8px 16px;
            background: rgba(16, 185, 129, 0.08);
            border-radius: 20px;
            border: 1px solid rgba(16, 185, 129, 0.2);
            margin-bottom: 12px;
            width: fit-content;
        }

        .security-scan-indicator.alert {
            color: var(--danger);
            background: rgba(244, 63, 94, 0.08);
            border: 1px solid rgba(244, 63, 94, 0.2);
        }
    </style>
</head>
<body>

    <div class="ambient-glow-1"></div>
    <div class="ambient-glow-2"></div>

    <!-- SIDEBAR -->
    <div class="sidebar">
        <div>
            <div class="brand">
                <div class="brand-logo">
                    <i class="fa-solid fa-arrows-spin"></i>
                </div>
                <div>
                    <h1 class="brand-title">DSE Meli Sync</h1>
                    <span style="font-size: 11px; color: var(--text-secondary); font-weight: 500;">Versão 1.1.0</span>
                </div>
            </div>
            
            <ul class="menu-list">
                <li class="menu-item active" onclick="switchTab('dashboard', this)">
                    <i class="fa-solid fa-chart-pie"></i> Dashboard
                </li>
                <li class="menu-item" onclick="switchTab('webhooks', this)">
                    <i class="fa-solid fa-code-fork"></i> Webhook Monitor
                </li>
                <li class="menu-item" onclick="switchTab('security', this)">
                    <i class="fa-solid fa-shield-halved"></i> Guardrails de Prompt
                </li>
                <li class="menu-item" onclick="switchTab('simulator', this)">
                    <i class="fa-solid fa-comments"></i> Vendedor Tester
                </li>
                <li class="menu-item" onclick="switchTab('catalog', this)">
                    <i class="fa-solid fa-boxes-stacked"></i> Catálogo Synced
                </li>
                <li class="menu-item" onclick="switchTab('manual', this)" style="border-top: 1px solid var(--border-glass); margin-top: 10px; border-radius: 0; padding-top: 15px;">
                    <i class="fa-solid fa-file-signature"></i> Cadastro Manual
                </li>
                <li class="menu-item" onclick="switchTab('analytics', this)">
                    <i class="fa-solid fa-chart-line"></i> Analytics Estoque
                </li>
            </ul>
        </div>

        <div class="sidebar-footer">
            <div class="system-status">
                <span>Serviços DSE</span>
                <div class="status-badge">
                    <div class="status-dot"></div>
                    <span style="color: white; font-weight: 600;">ONLINE</span>
                </div>
            </div>
            <span style="font-size: 10px; color: var(--text-secondary);">Desenv. por Data Science Enthusiasts</span>
        </div>
    </div>

    <!-- MAIN PANE -->
    <div class="main-content">
        <!-- HEADER -->
        <div class="header">
            <h2 class="header-title" id="panel-title">Painel de Monitoramento</h2>
            <div class="header-actions">
                <button class="btn" onclick="loadAllData()">
                    <i class="fa-solid fa-rotate"></i> Atualizar Painel
                </button>
                <a href="/docs" target="_blank" class="btn btn-primary" style="text-decoration: none;">
                    <i class="fa-solid fa-book"></i> Docs API
                </a>
            </div>
        </div>

        <!-- WORKSPACE views -->
        <div class="workspace">
            
            <!-- VIEW: DASHBOARD -->
            <div id="panel-dashboard" class="view-panel active">
                <div class="grid-stats">
                    <div class="stat-card">
                        <div>
                            <span class="stat-label">Total Webhooks</span>
                            <div class="stat-value" id="stats-total-webhooks">0</div>
                        </div>
                        <div class="stat-icon purple">
                            <i class="fa-solid fa-tower-broadcast"></i>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div>
                            <span class="stat-label">Processados OK</span>
                            <div class="stat-value" id="stats-webhooks-ok" style="color: var(--success);">0</div>
                        </div>
                        <div class="stat-icon green">
                            <i class="fa-solid fa-check-double"></i>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div>
                            <span class="stat-label">Erros / Bloqueios</span>
                            <div class="stat-value" id="stats-webhooks-failed" style="color: var(--danger);">0</div>
                        </div>
                        <div class="stat-icon red">
                            <i class="fa-solid fa-triangle-exclamation"></i>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div>
                            <span class="stat-label">Itens no Catálogo</span>
                            <div class="stat-value" id="stats-total-products">0</div>
                        </div>
                        <div class="stat-icon cyan">
                            <i class="fa-solid fa-box-open"></i>
                        </div>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px;">
                    <!-- Integration Summary -->
                    <div class="glass-card" style="margin-bottom: 0;">
                        <div class="card-header">
                            <h3 class="card-title"><i class="fa-solid fa-link"></i> Integração de Canais</h3>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 16px;">
                            <div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.05);">
                                <span style="color: var(--text-secondary);">Mercado Livre API Status</span>
                                <span id="status-meli" class="badge">Checking...</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.05);">
                                <span style="color: var(--text-secondary);">Provedor LLM Principal</span>
                                <span id="status-llm-provider" class="badge badge-info">Gemini</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.05);">
                                <span style="color: var(--text-secondary);">Detector de Prompt Injection</span>
                                <span class="badge badge-success">Ativado</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; padding: 12px 0;">
                                <span style="color: var(--text-secondary);">Criptografia de Prompt</span>
                                <span class="badge badge-success">AES-256-GCM Ativa</span>
                            </div>
                        </div>
                    </div>

                    <!-- Latest System Logs -->
                    <div class="glass-card" style="margin-bottom: 0; display: flex; flex-direction: column;">
                        <div class="card-header">
                            <h3 class="card-title"><i class="fa-solid fa-clock-rotate-left"></i> Webhooks Recentes</h3>
                        </div>
                        <div class="table-container" style="flex: 1; max-height: 220px; overflow-y: auto;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Tópico</th>
                                        <th>Recurso</th>
                                        <th>Status</th>
                                    </tr>
                                </thead>
                                <tbody id="dashboard-webhooks-list">
                                    <!-- Populated dynamically -->
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            <!-- VIEW: WEBHOOKS -->
            <div id="panel-webhooks" class="view-panel">
                <div class="glass-card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="fa-solid fa-code"></i> Monitor de Webhooks do Mercado Livre</h3>
                        <span style="font-size: 13px; color: var(--text-secondary);">Logs dinâmicos (PostgreSQL JSONB)</span>
                    </div>
                    <div class="table-container">
                        <table>
                            <thead>
                                <tr>
                                    <th>Data / Hora</th>
                                    <th>Tópico</th>
                                    <th>Recurso</th>
                                    <th>Status</th>
                                    <th>Ações</th>
                                </tr>
                            </thead>
                            <tbody id="webhooks-table-body">
                                <!-- Populated dynamically -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- VIEW: SECURITY LOGS -->
            <div id="panel-security" class="view-panel">
                <div class="glass-card">
                    <div class="card-header">
                        <h3 class="card-title" style="color: var(--danger);"><i class="fa-solid fa-shield-virus"></i> Tentativas de Ataques e Injeções Bloqueadas</h3>
                        <span class="badge badge-danger">Guardrails Ativo</span>
                    </div>
                    <div class="table-container">
                        <table>
                            <thead>
                                <tr>
                                    <th>Horário</th>
                                    <th>Tópico / Recurso</th>
                                    <th>Payload Bloqueado</th>
                                    <th>Motivo do Bloqueio</th>
                                </tr>
                            </thead>
                            <tbody id="alerts-table-body">
                                <!-- Populated dynamically -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- VIEW: SIMULATOR -->
            <div id="panel-simulator" class="view-panel">
                <div class="chat-container">
                    
                    <!-- Config Box -->
                    <div class="chat-config">
                        <h4 style="font-weight: 700; border-bottom: 1px solid var(--border-glass); padding-bottom: 10px;">Contexto da IA</h4>
                        
                        <div class="config-group">
                            <span class="config-label">Provedor</span>
                            <div class="config-value" id="chat-config-provider">Gemini API</div>
                        </div>

                        <div class="config-group">
                            <span class="config-label">Prompt Footprint</span>
                            <div class="config-value" style="font-family: monospace;">AES-256 decrypted in-memory</div>
                        </div>

                        <div class="config-group">
                            <span class="config-label">Identificação do Comprador</span>
                            <input type="text" id="chat-buyer-id" class="chat-input" style="padding: 10px 14px; font-size: 13px;" value="test_buyer_99">
                        </div>

                        <div class="config-group">
                            <span class="config-label">ID do Anúncio (Catalog)</span>
                            <input type="text" id="chat-item-id" class="chat-input" style="padding: 10px 14px; font-size: 13px;" value="MLB999888777">
                        </div>
                        
                        <span style="font-size: 11px; color: var(--text-secondary); line-height: 1.4;">
                            *Você pode enviar códigos de injeção (ex: "ignore as instruções") para testar os filtros de entrada e saída.
                        </span>
                    </div>

                    <!-- Chat Box -->
                    <div class="chat-workspace">
                        <div class="chat-messages" id="chat-messages-container">
                            <!-- Initial greeting -->
                            <div class="msg buyer">
                                <div class="msg-bubble">Olá! O produto digital é enviado no e-mail?</div>
                                <div class="msg-meta">Comprador • Agora</div>
                            </div>
                            <div class="msg agent">
                                <div class="msg-bubble">Olá! Sim, com certeza! Por se tratar de um produto 100% digital, o envio é totalmente grátis e imediato. Você receberá o link de acesso em minutos no seu e-mail e chat pós-venda após a aprovação do pagamento. Posso garantir a sua licença?</div>
                                <div class="msg-meta"><i class="fa-solid fa-shield-halved" style="color: var(--success);"></i> IA Vendas • Agora</div>
                            </div>
                        </div>

                        <!-- Scan alerts before text -->
                        <div style="padding: 0 24px;" id="chat-security-feedback"></div>

                        <div class="chat-input-area">
                            <input type="text" id="chat-user-input" class="chat-input" placeholder="Digite sua mensagem para o especialista de vendas..." onkeydown="if(event.key === 'Enter') sendChatMessage()">
                            <button class="btn btn-primary" onclick="sendChatMessage()">
                                <i class="fa-solid fa-paper-plane"></i>
                            </button>
                        </div>
                    </div>

                </div>
            </div>

            <!-- VIEW: CATALOG -->
            <div id="panel-catalog" class="view-panel">
                <div class="glass-card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="fa-solid fa-cubes"></i> Catálogo de Produtos Espelhado</h3>
                        <span style="font-size: 13px; color: var(--text-secondary);">Sincronização via Webhooks</span>
                    </div>
                    
                    <div style="display: flex; gap: 16px; margin-bottom: 24px; align-items: center; background: rgba(255,255,255,0.02); padding: 16px; border-radius: 12px; border: 1px solid var(--border-glass); flex-wrap: wrap;">
                        <span style="font-size: 14px; font-weight: 600; color: var(--text-secondary);">Sincronizar Novo ID do Mercado Livre:</span>
                        <input type="text" id="catalog-sync-id" class="chat-input" style="padding: 10px 16px; width: 220px; font-size: 13px; margin: 0;" placeholder="Ex: MLB999888777">
                        <button class="btn btn-primary" onclick="syncProductFromUI()" style="padding: 10px 18px; font-size: 13px; cursor: pointer;">
                            <i class="fa-solid fa-rotate"></i> Sincronizar Produto
                        </button>
                    </div>
                    <div class="table-container">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID do Item</th>
                                    <th>Título do Anúncio</th>
                                    <th>Preço</th>
                                    <th>Estoque</th>
                                    <th>Status</th>
                                    <th>Formato</th>
                                </tr>
                            </thead>
                            <tbody id="catalog-table-body">
                                <!-- Populated dynamically -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- VIEW: CADASTRO MANUAL -->
            <div id="panel-manual" class="view-panel">
                
                <!-- Supplier Form & List Section -->
                <div style="display: grid; grid-template-columns: 1fr 1.5fr; gap: 24px; margin-bottom: 24px;">
                    <!-- Supplier Form -->
                    <div class="glass-card" style="margin-bottom: 0;">
                        <div class="card-header">
                            <h3 class="card-title"><i class="fa-solid fa-handshake"></i> Novo Fornecedor</h3>
                        </div>
                        <form id="supplier-form" onsubmit="event.preventDefault(); submitSupplier();" style="display: flex; flex-direction: column; gap: 14px;">
                            <div class="form-group">
                                <label for="sup-name">Razão Social / Nome</label>
                                <input type="text" id="sup-name" class="form-input" placeholder="Ex: Distribuidora DSE Ltda" required>
                            </div>
                            <div class="form-group">
                                <label for="sup-contact">Contato (E-mail/Telefone)</label>
                                <input type="text" id="sup-contact" class="form-input" placeholder="Ex: contato@dse.com.br">
                            </div>
                            <button type="submit" class="btn btn-primary" style="margin-top: 10px; justify-content: center;">
                                <i class="fa-solid fa-plus"></i> Cadastrar Fornecedor
                            </button>
                        </form>
                    </div>

                    <!-- Supplier List -->
                    <div class="glass-card" style="margin-bottom: 0; display: flex; flex-direction: column;">
                        <div class="card-header">
                            <h3 class="card-title"><i class="fa-solid fa-list-check"></i> Fornecedores Cadastrados</h3>
                        </div>
                        <div class="table-container" style="flex: 1; max-height: 180px; overflow-y: auto;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Nome</th>
                                        <th>Contato</th>
                                    </tr>
                                </thead>
                                <tbody id="supplier-table-body">
                                    <!-- Populated dynamically -->
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Product Manual Form -->
                <div class="glass-card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="fa-solid fa-barcode"></i> Novo Produto Manual</h3>
                        <span style="font-weight: 700; color: var(--accent-secondary);" id="calc-total-preview">Total Estimado: R$ 0,00</span>
                    </div>
                    <form id="manual-product-form" onsubmit="event.preventDefault(); submitManualProduct();">
                        <div class="form-grid">
                            <div class="form-group">
                                <label for="prod-barcode">Código de Barras</label>
                                <input type="text" id="prod-barcode" class="form-input" placeholder="Ex: 789100010001" required>
                            </div>
                            <div class="form-group">
                                <label for="prod-reference">Referência / SKU</label>
                                <input type="text" id="prod-reference" class="form-input" placeholder="Ex: REF-1002">
                            </div>
                            <div class="form-group">
                                <label for="prod-supplier">Fornecedor</label>
                                <select id="prod-supplier" class="form-input" required>
                                    <option value="">Selecione um fornecedor...</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label for="prod-category">Categoria</label>
                                <input type="text" id="prod-category" class="form-input" placeholder="Ex: Eletronicos" required>
                            </div>
                        </div>

                        <div class="form-grid">
                            <div class="form-group">
                                <label for="prod-subcategory">Subcategoria</label>
                                <input type="text" id="prod-subcategory" class="form-input" placeholder="Ex: Smartphones">
                            </div>
                            <div class="form-group">
                                <label for="prod-quantity">Quantidade</label>
                                <input type="number" id="prod-quantity" class="form-input" value="1" min="1" oninput="updateTotalPreview()" required>
                            </div>
                            <div class="form-group">
                                <label for="prod-unit-value">Valor Unitário (R$)</label>
                                <input type="number" id="prod-unit-value" class="form-input" step="0.01" value="0.00" min="0.00" oninput="updateTotalPreview()" required>
                            </div>
                            <div class="form-group">
                                <label for="prod-discount">Desconto Total (R$)</label>
                                <input type="number" id="prod-discount" class="form-input" step="0.01" value="0.00" min="0.00" oninput="updateTotalPreview()">
                            </div>
                        </div>

                        <div class="form-grid" style="grid-template-columns: 1fr 2fr;">
                            <div class="form-group">
                                <label for="prod-price-type">Tipo de Preço</label>
                                <select id="prod-price-type" class="form-input" onchange="updateTotalPreview()" required>
                                    <option value="normal">Normal</option>
                                    <option value="consignado">Consignado</option>
                                    <option value="brinde">Brinde</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label for="prod-description">Descrição do Produto</label>
                                <input type="text" id="prod-description" class="form-input" placeholder="Ex: Smartphone DSE Pro 128GB" required>
                            </div>
                        </div>

                        <button type="submit" class="btn btn-primary" style="width: 100%; justify-content: center; padding: 14px;">
                            <i class="fa-solid fa-check"></i> Cadastrar Produto no Estoque
                        </button>
                    </form>
                </div>

                <!-- Manual Products List -->
                <div class="glass-card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="fa-solid fa-clipboard-list"></i> Produtos no Estoque Manual</h3>
                    </div>
                    <div class="table-container">
                        <table>
                            <thead>
                                <tr>
                                    <th>Cód. Barras</th>
                                    <th>Referência</th>
                                    <th>Descrição</th>
                                    <th>Qtd.</th>
                                    <th>V. Unitário</th>
                                    <th>Desconto</th>
                                    <th>Total Estoque</th>
                                    <th>Tipo Preço</th>
                                    <th>Fornecedor</th>
                                    <th>Ações</th>
                                </tr>
                            </thead>
                            <tbody id="manual-products-table-body">
                                <!-- Populated dynamically -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- VIEW: ANALYTICS (NEW!) -->
            <div id="panel-analytics" class="view-panel">
                
                <!-- Target Settings Row -->
                <div class="glass-card" style="padding: 16px 24px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <i class="fa-solid fa-sliders" style="color: var(--accent-secondary);"></i>
                            <h4 style="font-weight: 700; font-size: 16px;">Metas e Créditos Corporativos</h4>
                        </div>
                        <div style="display: flex; gap: 16px; align-items: center;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <label for="cfg-meta" style="font-size: 12px; font-weight: 600; color: var(--text-secondary);">META VENDAS (R$):</label>
                                <input type="number" id="cfg-meta" class="form-input" style="padding: 8px 12px; width: 140px; margin: 0; font-size: 13px;" value="10000">
                            </div>
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <label for="cfg-credits" style="font-size: 12px; font-weight: 600; color: var(--text-secondary);">CRÉDITOS (R$):</label>
                                <input type="number" id="cfg-credits" class="form-input" style="padding: 8px 12px; width: 140px; margin: 0; font-size: 13px;" value="5000">
                            </div>
                            <button class="btn btn-primary" onclick="saveSystemConfig()" style="padding: 8px 16px; font-size: 13px;">
                                <i class="fa-solid fa-save"></i> Salvar
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Metrics KPIs (6 columns layout) -->
                <div class="grid-stats" style="grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));">
                    <div class="stat-card">
                        <div>
                            <span class="stat-label">Qtd Total Itens</span>
                            <div class="stat-value" id="analytics-total-qty">0</div>
                        </div>
                        <div class="stat-icon purple">
                            <i class="fa-solid fa-boxes-packing"></i>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div>
                            <span class="stat-label">Val Estoque (Net)</span>
                            <div class="stat-value" id="analytics-total-val" style="color: var(--success);">R$ 0,00</div>
                        </div>
                        <div class="stat-icon green">
                            <i class="fa-solid fa-money-bill-trend-up"></i>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div>
                            <span class="stat-label">Descontos Estoque</span>
                            <div class="stat-value" id="analytics-total-discount" style="color: var(--warning);">R$ 0,00</div>
                        </div>
                        <div class="stat-icon yellow">
                            <i class="fa-solid fa-tags"></i>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div>
                            <span class="stat-label">Faturamento Total</span>
                            <div class="stat-value" id="analytics-total-sales" style="color: #22c55e; font-weight: 800;">R$ 0,00</div>
                        </div>
                        <div class="stat-icon green" style="background: rgba(34,197,94,0.15); border-color: rgba(34,197,94,0.3);">
                            <i class="fa-solid fa-dollar-sign"></i>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div>
                            <span class="stat-label">Itens Vendidos</span>
                            <div class="stat-value" id="analytics-sales-qty" style="color: var(--accent-secondary);">0</div>
                        </div>
                        <div class="stat-icon cyan">
                            <i class="fa-solid fa-basket-shopping"></i>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div>
                            <span class="stat-label">Créditos Ativos</span>
                            <div class="stat-value" id="analytics-credits" style="color: var(--text-primary);">R$ 0,00</div>
                        </div>
                        <div class="stat-icon purple">
                            <i class="fa-solid fa-hand-holding-dollar"></i>
                        </div>
                    </div>
                </div>

                <!-- Meta Progress Card -->
                <div class="glass-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <span class="stat-label" style="font-weight: 700;">Acompanhamento de Meta de Faturamento de Vendas</span>
                        <span id="analytics-meta-progress-text" style="font-weight: 700; color: var(--accent-secondary);">0% atingido</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 13px; color: var(--text-secondary); margin-bottom: 8px;">
                        <span>Faturado: <strong id="analytics-meta-current" style="color: white;">R$ 0,00</strong></span>
                        <span>Meta de Vendas: <strong id="analytics-meta-target" style="color: white;">R$ 0,00</strong></span>
                    </div>
                    <div class="progress-wrapper">
                        <div class="progress-bar-bg">
                            <div class="progress-bar-fill" id="analytics-meta-progress-bar"></div>
                        </div>
                    </div>
                </div>

                <!-- Distributions layout -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 24px;">
                    <!-- Category table -->
                    <div class="glass-card" style="margin-bottom: 0;">
                        <div class="card-header">
                            <h3 class="card-title"><i class="fa-solid fa-layer-group"></i> Distribuição por Categoria</h3>
                        </div>
                        <div class="table-container" style="max-height: 250px; overflow-y: auto;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Categoria</th>
                                        <th>Qtd. Itens</th>
                                        <th>Valor Acumulado</th>
                                    </tr>
                                </thead>
                                <tbody id="analytics-category-tbody">
                                    <!-- Populated dynamically -->
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- Subcategory table -->
                    <div class="glass-card" style="margin-bottom: 0;">
                        <div class="card-header">
                            <h3 class="card-title"><i class="fa-solid fa-network-wired"></i> Distribuição por Subcategoria</h3>
                        </div>
                        <div class="table-container" style="max-height: 250px; overflow-y: auto;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Subcategoria</th>
                                        <th>Qtd. Itens</th>
                                        <th>Valor Acumulado</th>
                                    </tr>
                                </thead>
                                <tbody id="analytics-subcategory-tbody">
                                    <!-- Populated dynamically -->
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Price Type distribution -->
                <div class="glass-card">
                    <div class="card-header">
                        <h3 class="card-title"><i class="fa-solid fa-receipt"></i> Métricas por Tipo de Preço (Estoque)</h3>
                    </div>
                    <div class="table-container">
                        <table>
                            <thead>
                                <tr>
                                    <th>Tipo de Preço</th>
                                    <th>Qtd. Itens</th>
                                    <th>Valor Total Liquido</th>
                                    <th>Participação</th>
                                </tr>
                            </thead>
                            <tbody id="analytics-type-tbody">
                                <!-- Populated dynamically -->
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- SALES HISTORY LOG (NEW!) -->
                <div class="glass-card" style="margin-top: 24px;">
                    <div class="card-header">
                        <h3 class="card-title" style="color: #22c55e;"><i class="fa-solid fa-receipt"></i> Histórico Recente de Vendas (Baixas de Estoque)</h3>
                    </div>
                    <div class="table-container" style="max-height: 280px; overflow-y: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>Data / Hora</th>
                                    <th>Descrição do Produto</th>
                                    <th>Quantidade</th>
                                    <th>Preço Unitário</th>
                                    <th>Faturamento da Venda</th>
                                </tr>
                            </thead>
                            <tbody id="analytics-sales-history-tbody">
                                <!-- Populated dynamically -->
                            </tbody>
                        </table>
                    </div>
                </div>

            </div>

        </div>
    </div>

    <!-- JSON VIEWER MODAL -->
    <div id="json-modal" class="modal" onclick="closeModal()">
        <div class="modal-content" onclick="event.stopPropagation()">
            <div class="modal-header">
                <h3 id="modal-title" style="font-weight: 700;">Detalhes do Webhook</h3>
                <button class="btn" style="padding: 6px 12px;" onclick="closeModal()">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
            <div class="modal-body">
                <pre class="json-viewer" id="modal-json-content"></pre>
            </div>
        </div>
    </div>

    <script>
        // Tab switching logic
        function switchTab(tabId, menuItem) {
            // Update active menu item
            document.querySelectorAll('.menu-item').forEach(item => {
                item.classList.remove('active');
            });
            menuItem.classList.add('active');

            // Update visible panel
            document.querySelectorAll('.view-panel').forEach(panel => {
                panel.classList.remove('active');
            });
            document.getElementById('panel-' + tabId).classList.add('active');

            // Update header title
            const titles = {
                'dashboard': 'Painel de Monitoramento',
                'webhooks': 'Monitor de Webhooks',
                'security': 'Central de Segurança e Guardrails',
                'simulator': 'AI Chat Simulator (Vendedor)',
                'catalog': 'Catálogo de Produtos',
                'manual': 'Cadastro Manual de Itens e Fornecedores',
                'analytics': 'Métricas e Analytics do Estoque'
            };
            document.getElementById('panel-title').innerText = titles[tabId];
            
            // Reload specific tab data
            if (tabId === 'manual') {
                loadManualTabData();
            } else if (tabId === 'analytics') {
                loadAnalyticsTabData();
            }
        }

        // Fetch Stats
        async function fetchStats() {
            try {
                const response = await fetch('/api/v1/admin/stats');
                const data = await response.json();
                
                document.getElementById('stats-total-webhooks').innerText = data.total_webhooks || 0;
                document.getElementById('stats-webhooks-ok').innerText = data.webhook_status?.processed || 0;
                document.getElementById('stats-webhooks-failed').innerText = data.webhook_status?.failed || 0;
                document.getElementById('stats-total-products').innerText = data.total_products || 0;
                
                const meliStatus = document.getElementById('status-meli');
                if (data.meli_authenticated) {
                    meliStatus.innerText = 'CONECTADO';
                    meliStatus.className = 'badge badge-success';
                } else {
                    meliStatus.innerText = 'MOCK / DESCONECTADO';
                    meliStatus.className = 'badge badge-warning';
                }

                document.getElementById('status-llm-provider').innerText = data.llm_provider ? data.llm_provider.toUpperCase() : 'DESCONHECIDO';
                document.getElementById('chat-config-provider').innerText = data.llm_provider ? data.llm_provider.toUpperCase() + ' API' : 'SIMULATION MOCK';
            } catch (err) {
                console.error("Error fetching stats:", err);
            }
        }

        // Fetch Webhooks
        async function fetchWebhooks() {
            try {
                const response = await fetch('/api/v1/admin/webhooks');
                const webhooks = await response.json();

                const tbodyFull = document.getElementById('webhooks-table-body');
                const tbodyDashboard = document.getElementById('dashboard-webhooks-list');

                tbodyFull.innerHTML = '';
                tbodyDashboard.innerHTML = '';

                webhooks.forEach((item, index) => {
                    const badgeClass = item.status === 'processed' ? 'badge-success' : (item.status === 'failed' ? 'badge-danger' : 'badge-info');
                    const formattedDate = new Date(item.created_at).toLocaleString('pt-BR');
                    
                    const rowFull = `
                        <tr>
                            <td style="color: var(--text-secondary); font-size: 13px;">${formattedDate}</td>
                            <td><span class="badge badge-info">${item.topic}</span></td>
                            <td style="font-family: monospace; font-size: 13px;">${item.resource}</td>
                            <td><span class="badge ${badgeClass}">${item.status.toUpperCase()}</span></td>
                            <td>
                                <button class="btn" style="padding: 6px 12px; font-size: 12px;" onclick="inspectWebhook('${encodeURIComponent(JSON.stringify(item.payload))}', '${item.topic}')">
                                    <i class="fa-solid fa-magnifying-glass"></i> Inspecionar
                                </button>
                            </td>
                        </tr>
                    `;
                    tbodyFull.innerHTML += rowFull;

                    if (index < 5) {
                        const rowDash = `
                            <tr>
                                <td><span class="badge badge-info">${item.topic}</span></td>
                                <td style="font-family: monospace; font-size: 12px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${item.resource}</td>
                                <td><span class="badge ${badgeClass}">${item.status}</span></td>
                            </tr>
                        `;
                        tbodyDashboard.innerHTML += rowDash;
                    }
                });
            } catch (err) {
                console.error("Error fetching webhooks:", err);
            }
        }

        // Fetch Alerts
        async function fetchAlerts() {
            try {
                const response = await fetch('/api/v1/admin/alerts');
                const alerts = await response.json();

                const tbody = document.getElementById('alerts-table-body');
                tbody.innerHTML = '';

                if (alerts.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="4" style="text-align: center; color: var(--text-secondary); padding: 40px;">
                                <i class="fa-solid fa-shield-circle-check" style="font-size: 32px; color: var(--success); margin-bottom: 10px; display: block;"></i>
                                Nenhum alerta de injeção ou vazamento de segurança detectado!
                            </td>
                        </tr>
                    `;
                    return;
                }

                alerts.forEach(item => {
                    const formattedDate = new Date(item.created_at).toLocaleString('pt-BR');
                    
                    let category = 'Ataque de Injeção';
                    let badgeColor = 'badge-danger';
                    if (item.error_message.includes('signature')) {
                        category = 'Assinatura Inválida';
                        badgeColor = 'badge-warning';
                    }

                    const row = `
                        <tr>
                            <td style="color: var(--text-secondary); font-size: 13px; font-family: monospace;">${formattedDate}</td>
                            <td><span class="badge ${badgeColor}">${category}</span></td>
                            <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; font-size: 13px; font-family: monospace; color: #a7f3d0;">
                                ${JSON.stringify(item.payload)}
                            </td>
                            <td style="color: var(--danger); font-size: 13px; font-weight: 500;">
                                ${item.error_message}
                            </td>
                        </tr>
                    `;
                    tbody.innerHTML += row;
                });
            } catch (err) {
                console.error("Error fetching alerts:", err);
            }
        }

        // Fetch Catalog
        async function fetchCatalog() {
            try {
                const response = await fetch('/api/v1/admin/products');
                const products = await response.json();

                const tbody = document.getElementById('catalog-table-body');
                tbody.innerHTML = '';

                if (products.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="6" style="text-align: center; color: var(--text-secondary); padding: 40px;">
                                <i class="fa-solid fa-box-open" style="font-size: 32px; margin-bottom: 10px; display: block;"></i>
                                Nenhum produto sincronizado no banco de dados local ainda.
                            </td>
                        </tr>
                    `;
                    return;
                }

                products.forEach(item => {
                    const format = item.attributes?.format || 'Físico / Padrão';
                    const row = `
                        <tr>
                            <td style="font-family: monospace; font-size: 13px;">${item.id}</td>
                            <td style="font-weight: 600;">${item.title}</td>
                            <td style="color: var(--accent-secondary); font-weight: 600;">R$ ${item.price.toFixed(2)}</td>
                            <td>${item.stock} unidades</td>
                            <td><span class="badge badge-success">${item.status.toUpperCase()}</span></td>
                            <td style="color: var(--text-secondary); font-size: 13px;">${format}</td>
                        </tr>
                    `;
                    tbody.innerHTML += row;
                });
            } catch (err) {
                console.error("Error fetching products:", err);
            }
        }

        // Send chat simulator message
        async function sendChatMessage() {
            const input = document.getElementById('chat-user-input');
            const messageText = input.value.trim();
            if (!messageText) return;

            input.value = '';

            const container = document.getElementById('chat-messages-container');
            const feedback = document.getElementById('chat-security-feedback');

            const userMsgHtml = `
                <div class="msg buyer">
                    <div class="msg-bubble">${messageText}</div>
                    <div class="msg-meta">Comprador • Agora</div>
                </div>
            `;
            container.innerHTML += userMsgHtml;
            container.scrollTop = container.scrollHeight;

            feedback.innerHTML = `
                <div class="security-scan-indicator">
                    <i class="fa-solid fa-spinner fa-spin"></i> Guardrail analisando entrada contra injeções...
                </div>
            `;

            const buyerId = document.getElementById('chat-buyer-id').value;
            const itemId = document.getElementById('chat-item-id').value;

            try {
                const response = await fetch('/api/v1/chat/message', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        buyer_id: buyerId,
                        item_id: itemId,
                        message: messageText
                    })
                });

                const data = await response.json();

                if (response.status === 400) {
                    feedback.innerHTML = `
                        <div class="security-scan-indicator alert">
                            <i class="fa-solid fa-shield-virus"></i> Injeção Detectada! O Guardrail bloqueou a mensagem.
                        </div>
                    `;
                    const agentMsgHtml = `
                        <div class="msg agent">
                            <div class="msg-bubble" style="background: rgba(244,63,94,0.1); border: 1px solid rgba(244,63,94,0.3); color: var(--danger);">
                                ${data.detail}
                            </div>
                            <div class="msg-meta"><i class="fa-solid fa-shield-halved" style="color: var(--danger);"></i> Guardrail Intercept • Agora</div>
                        </div>
                    `;
                    container.innerHTML += agentMsgHtml;
                } else if (!response.ok) {
                    throw new Error("API Error");
                } else {
                    feedback.innerHTML = `
                        <div class="security-scan-indicator">
                            <i class="fa-solid fa-shield-halved"></i> Guardrails de entrada e saída validados com sucesso (Conformidade 100%)
                        </div>
                    `;
                    
                    const agentMsgHtml = `
                        <div class="msg agent">
                            <div class="msg-bubble">${data.response}</div>
                            <div class="msg-meta"><i class="fa-solid fa-shield-halved" style="color: var(--success);"></i> IA Vendas (AES-256 GCM) • Agora</div>
                        </div>
                    `;
                    container.innerHTML += agentMsgHtml;
                }
            } catch (err) {
                feedback.innerHTML = '';
                const errorHtml = `
                    <div class="msg agent">
                        <div class="msg-bubble" style="background: rgba(255,255,255,0.05); color: var(--warning);">
                            Desculpe, ocorreu uma falha ao conectar com o serviço do assistente de vendas.
                        </div>
                        <div class="msg-meta">Sistema • Agora</div>
                    </div>
                `;
                container.innerHTML += errorHtml;
            }

            container.scrollTop = container.scrollHeight;
            
            setTimeout(() => {
                feedback.innerHTML = '';
            }, 4000);

            fetchStats();
        }

        // Inspect Webhook in JSON modal
        function inspectWebhook(encodedPayload, topic) {
            const payload = JSON.parse(decodeURIComponent(encodedPayload));
            document.getElementById('modal-title').innerHTML = `<i class="fa-solid fa-code"></i> Payload do Webhook: ${topic.toUpperCase()}`;
            document.getElementById('modal-json-content').innerText = JSON.stringify(payload, null, 2);
            document.getElementById('json-modal').style.display = 'flex';
        }

        function closeModal() {
            document.getElementById('json-modal').style.display = 'none';
        }

        // Sync product from ML catalog
        async function syncProductFromUI() {
            const input = document.getElementById('catalog-sync-id');
            const itemId = input.value.trim();
            if (!itemId) {
                alert("Por favor, digite um ID do Mercado Livre.");
                return;
            }

            try {
                const response = await fetch('/api/v1/admin/products', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_id: itemId })
                });

                const data = await response.json();
                if (response.ok) {
                    alert(data.message || "Produto sincronizado!");
                    input.value = '';
                    loadAllData();
                } else {
                    alert("Erro ao sincronizar: " + (data.detail || "Erro desconhecido"));
                }
            } catch (err) {
                alert("Erro ao se conectar com o servidor.");
            }
        }


        // ==========================================
        // --- MANUAL PRODUCTS & SUPPLIERS & SALES ---
        // ==========================================

        // Calculate and update the estimated total value dynamically in form
        function updateTotalPreview() {
            const qty = parseInt(document.getElementById('prod-quantity').value) || 0;
            const unitVal = parseFloat(document.getElementById('prod-unit-value').value) || 0.0;
            const discount = parseFloat(document.getElementById('prod-discount').value) || 0.0;
            const priceType = document.getElementById('prod-price-type').value;

            let total = 0.0;
            if (priceType === 'brinde') {
                total = 0.0;
                document.getElementById('prod-unit-value').disabled = true;
                document.getElementById('prod-discount').disabled = true;
            } else {
                document.getElementById('prod-unit-value').disabled = false;
                document.getElementById('prod-discount').disabled = false;
                total = (qty * unitVal) - discount;
                if (total < 0.0) total = 0.0;
            }

            document.getElementById('calc-total-preview').innerText = `Total Estimado: R$ ${total.toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
        }

        // Fetch Suppliers
        async function fetchSuppliers() {
            try {
                const response = await fetch('/api/v1/manual-products/suppliers');
                const suppliers = await response.json();
                
                const tableBody = document.getElementById('supplier-table-body');
                const selectElement = document.getElementById('prod-supplier');
                
                tableBody.innerHTML = '';
                selectElement.innerHTML = '<option value="">Selecione um fornecedor...</option>';

                if (suppliers.length === 0) {
                    tableBody.innerHTML = '<tr><td colspan="2" style="text-align: center; color: var(--text-secondary);">Nenhum fornecedor cadastrado.</td></tr>';
                    return;
                }

                suppliers.forEach(item => {
                    const row = `
                        <tr>
                            <td style="font-weight: 600;">${item.name}</td>
                            <td style="color: var(--text-secondary); font-size: 13px;">${item.contact || 'Sem contato'}</td>
                        </tr>
                    `;
                    tableBody.innerHTML += row;
                    selectElement.innerHTML += `<option value="${item.id}">${item.name}</option>`;
                });
            } catch (err) {
                console.error("Error fetching suppliers:", err);
            }
        }

        // Submit Supplier
        async function submitSupplier() {
            const nameInput = document.getElementById('sup-name');
            const contactInput = document.getElementById('sup-contact');
            
            const payload = {
                name: nameInput.value.trim(),
                contact: contactInput.value.trim() || null
            };

            try {
                const response = await fetch('/api/v1/manual-products/suppliers', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (response.ok) {
                    nameInput.value = '';
                    contactInput.value = '';
                    await fetchSuppliers();
                } else {
                    const err = await response.json();
                    alert("Erro ao cadastrar fornecedor: " + (err.detail || "Erro de rede"));
                }
            } catch (err) {
                alert("Erro ao comunicar com o servidor.");
            }
        }

        // Fetch Manual Products
        async function fetchManualProducts() {
            try {
                const response = await fetch('/api/v1/manual-products');
                const products = await response.json();
                const tbody = document.getElementById('manual-products-table-body');
                tbody.innerHTML = '';

                if (products.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--text-secondary); padding: 20px;">Nenhum produto cadastrado manualmente no estoque.</td></tr>';
                    return;
                }

                products.forEach(item => {
                    const typeBadge = item.price_type === 'consignado' ? 'badge-info' : (item.price_type === 'brinde' ? 'badge-warning' : 'badge-success');
                    
                    const row = `
                        <tr>
                            <td style="font-family: monospace; font-size: 12px; color: var(--text-secondary);">${item.barcode}</td>
                            <td style="font-family: monospace; font-size: 12px;">${item.reference || '-'}</td>
                            <td style="font-weight: 500;">${item.description}</td>
                            <td><strong>${item.quantity}</strong></td>
                            <td>R$ ${item.unit_value.toFixed(2)}</td>
                            <td style="color: var(--danger);">R$ ${item.discount.toFixed(2)}</td>
                            <td style="color: var(--success); font-weight: 700;">R$ ${item.total_value.toFixed(2)}</td>
                            <td><span class="badge ${typeBadge}">${item.price_type.toUpperCase()}</span></td>
                            <td style="color: var(--text-secondary); font-size: 13px;">${item.supplier_name}</td>
                            <td>
                                <div style="display: flex; gap: 8px;">
                                    <button class="btn btn-primary" style="padding: 6px 10px; font-size: 12px; background: linear-gradient(135deg, var(--accent-secondary) 0%, rgba(6, 182, 212, 0.6) 100%);" onclick="sellManualProductPrompt('${item.id}', '${item.description}', ${item.quantity}, ${item.unit_value})">
                                        <i class="fa-solid fa-cart-shopping"></i> Vender
                                    </button>
                                    <button class="btn btn-danger" style="padding: 6px 10px; font-size: 12px;" onclick="deleteManualProduct('${item.id}')">
                                        <i class="fa-solid fa-trash"></i> Excluir
                                    </button>
                                </div>
                            </td>
                        </tr>
                    `;
                    tbody.innerHTML += row;
                });
            } catch (err) {
                console.error("Error fetching manual products:", err);
            }
        }

        // Submit Manual Product
        async function submitManualProduct() {
            const barcode = document.getElementById('prod-barcode').value.trim();
            const reference = document.getElementById('prod-reference').value.trim();
            const supplierId = document.getElementById('prod-supplier').value;
            const category = document.getElementById('prod-category').value.trim();
            const subcategory = document.getElementById('prod-subcategory').value.trim();
            const quantity = parseInt(document.getElementById('prod-quantity').value) || 0;
            const unitValue = parseFloat(document.getElementById('prod-unit-value').value) || 0.0;
            const discount = parseFloat(document.getElementById('prod-discount').value) || 0.0;
            const priceType = document.getElementById('prod-price-type').value;
            const description = document.getElementById('prod-description').value.trim();

            if (!supplierId) {
                alert("Por favor, selecione um Fornecedor cadastrado.");
                return;
            }

            const payload = {
                barcode: barcode,
                reference: reference || null,
                supplier_id: supplierId,
                category: category,
                subcategory: subcategory || null,
                quantity: quantity,
                unit_value: unitValue,
                discount: discount,
                price_type: priceType,
                description: description
            };

            try {
                const response = await fetch('/api/v1/manual-products', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (response.ok) {
                    document.getElementById('manual-product-form').reset();
                    updateTotalPreview();
                    await fetchManualProducts();
                } else {
                    const err = await response.json();
                    alert("Erro ao cadastrar produto: " + (err.detail || "Erro de rede"));
                }
            } catch (err) {
                alert("Erro ao se conectar com o servidor.");
            }
        }

        // Prompt user and submit sale
        async function sellManualProductPrompt(productId, description, maxQty, defaultPrice) {
            if (maxQty <= 0) {
                alert("Este produto nao possui unidades no estoque para serem vendidas!");
                return;
            }

            const qtyStr = prompt(`Registrar baixa por Venda para: ${description}\nEstoque Atual: ${maxQty}\n\nDigite a quantidade a ser vendida:`, "1");
            if (qtyStr === null) return;
            const qty = parseInt(qtyStr);
            if (isNaN(qty) || qty <= 0) {
                alert("Quantidade inserida invalida.");
                return;
            }
            if (qty > maxQty) {
                alert(`Quantidade indisponivel. O estoque atual e de apenas ${maxQty} unidades.`);
                return;
            }

            const priceStr = prompt(`Digite o preco unitario cobrado na venda (R$):`, defaultPrice.toFixed(2));
            if (priceStr === null) return;
            const price = parseFloat(priceStr);
            if (isNaN(price) || price < 0.0) {
                alert("Preco inserido invalido.");
                return;
            }

            const payload = {
                quantity: qty,
                unit_price: price
            };

            try {
                const response = await fetch(`/api/v1/manual-products/${productId}/sell`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const resData = await response.json();
                if (response.ok) {
                    alert(resData.message);
                    await fetchManualProducts();
                    if (document.getElementById('panel-analytics').classList.contains('active')) {
                        await loadAnalyticsTabData();
                    }
                } else {
                    alert("Erro ao efetuar baixa: " + (resData.detail || "Erro desconhecido"));
                }
            } catch (err) {
                alert("Erro ao se conectar com o servidor.");
            }
        }

        // Delete Manual Product
        async function deleteManualProduct(productId) {
            if (!confirm("Tem certeza de que deseja excluir este produto do estoque manual?")) {
                return;
            }

            try {
                const response = await fetch(`/api/v1/manual-products/${productId}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    await fetchManualProducts();
                } else {
                    const err = await response.json();
                    alert("Erro ao excluir produto: " + (err.detail || "Erro de rede"));
                }
            } catch (err) {
                alert("Erro ao se conectar com o servidor.");
            }
        }

        // Load config
        async function fetchSystemConfig() {
            try {
                const response = await fetch('/api/v1/manual-products/config');
                const data = await response.json();
                
                document.getElementById('cfg-meta').value = data.meta;
                document.getElementById('cfg-credits').value = data.credits;
            } catch (err) {
                console.error("Error fetching configs:", err);
            }
        }

        // Save system config (credits / meta)
        async function saveSystemConfig() {
            const meta = parseFloat(document.getElementById('cfg-meta').value) || 0.0;
            const credits = parseFloat(document.getElementById('cfg-credits').value) || 0.0;

            const payload = { meta: meta, credits: credits };

            try {
                const response = await fetch('/api/v1/manual-products/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (response.ok) {
                    alert("Configurações atualizadas!");
                    await loadAnalyticsTabData();
                } else {
                    alert("Falha ao salvar as configurações.");
                }
            } catch (err) {
                alert("Erro ao se conectar com o servidor.");
            }
        }

        // Fetch sales history table
        async function fetchSalesHistory() {
            try {
                const response = await fetch('/api/v1/manual-products/sales');
                const sales = await response.json();
                const tbody = document.getElementById('analytics-sales-history-tbody');
                tbody.innerHTML = '';

                if (sales.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-secondary); padding: 15px;">Nenhuma baixa ou venda efetuada ainda.</td></tr>';
                    return;
                }

                sales.forEach(item => {
                    const formattedDate = new Date(item.sold_at).toLocaleString('pt-BR');
                    tbody.innerHTML += `
                        <tr>
                            <td style="color: var(--text-secondary); font-size: 13px;">${formattedDate}</td>
                            <td style="font-weight: 600;">${item.product_description}</td>
                            <td><strong>${item.quantity}</strong></td>
                            <td>R$ ${item.unit_price.toFixed(2)}</td>
                            <td style="color: #22c55e; font-weight: 700;">R$ ${item.total_value.toFixed(2)}</td>
                        </tr>
                    `;
                });
            } catch (err) {
                console.error("Error fetching sales history:", err);
            }
        }

        // Load and compile advanced metrics
        async function loadAnalyticsTabData() {
            await fetchSystemConfig();
            await fetchSalesHistory();
            
            try {
                const response = await fetch('/api/v1/manual-products/analytics');
                const data = await response.json();
                
                // Set summary numbers
                document.getElementById('analytics-total-qty').innerText = data.summary.total_quantity;
                document.getElementById('analytics-total-val').innerText = `R$ ${data.summary.total_value.toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
                document.getElementById('analytics-total-discount').innerText = `R$ ${data.summary.total_discount.toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
                document.getElementById('analytics-credits').innerText = `R$ ${data.summary.credits.toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
                
                // Sales numbers
                document.getElementById('analytics-total-sales').innerText = `R$ ${data.summary.total_sales_value.toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
                document.getElementById('analytics-sales-qty').innerText = data.summary.total_sales_quantity;
                
                // Meta Tracking text
                document.getElementById('analytics-meta-progress-text').innerText = `${data.summary.meta_progress_percentage}% atingido`;
                document.getElementById('analytics-meta-current').innerText = `R$ ${data.summary.total_sales_value.toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
                document.getElementById('analytics-meta-target').innerText = `R$ ${data.summary.meta.toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
                
                // Progress Bar fill
                const progressFill = Math.min(data.summary.meta_progress_percentage, 100);
                document.getElementById('analytics-meta-progress-bar').style.width = `${progressFill}%`;

                // Render Categories distribution Table
                const catTbody = document.getElementById('analytics-category-tbody');
                catTbody.innerHTML = '';
                if (data.by_category.length === 0) {
                    catTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-secondary);">Sem dados de categoria.</td></tr>';
                } else {
                    data.by_category.forEach(item => {
                        catTbody.innerHTML += `
                            <tr>
                                <td style="font-weight: 600;">${item.category}</td>
                                <td>${item.quantity} itens</td>
                                <td style="color: var(--accent-secondary); font-weight: 600;">R$ ${item.total_value.toFixed(2)}</td>
                            </tr>
                        `;
                    });
                }

                // Render Subcategories distribution Table
                const subTbody = document.getElementById('analytics-subcategory-tbody');
                subTbody.innerHTML = '';
                if (data.by_subcategory.length === 0) {
                    subTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-secondary);">Sem dados de subcategoria.</td></tr>';
                } else {
                    data.by_subcategory.forEach(item => {
                        subTbody.innerHTML += `
                            <tr>
                                <td style="font-weight: 600;">${item.subcategory}</td>
                                <td>${item.quantity} itens</td>
                                <td style="color: var(--accent-secondary); font-weight: 600;">R$ ${item.total_value.toFixed(2)}</td>
                            </tr>
                        `;
                    });
                }

                // Render Price Type distribution Table
                const typeTbody = document.getElementById('analytics-type-tbody');
                typeTbody.innerHTML = '';
                if (data.by_price_type.length === 0) {
                    typeTbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-secondary);">Sem dados de tipo de preço.</td></tr>';
                } else {
                    data.by_price_type.forEach(item => {
                        const totalStockVal = data.summary.total_value;
                        const percentage = totalStockVal > 0.0 ? ((item.total_value / totalStockVal) * 100.0).toFixed(1) + '%' : '0.0%';
                        const badgeColor = item.price_type === 'consignado' ? 'badge-info' : (item.price_type === 'brinde' ? 'badge-warning' : 'badge-success');

                        typeTbody.innerHTML += `
                            <tr>
                                <td><span class="badge ${badgeColor}">${item.price_type.toUpperCase()}</span></td>
                                <td><strong>${item.quantity} unidades</strong></td>
                                <td style="color: var(--success); font-weight: 700;">R$ ${item.total_value.toFixed(2)}</td>
                                <td style="font-weight: 600;">${percentage}</td>
                            </tr>
                        `;
                    });
                }

            } catch (err) {
                console.error("Error loading analytics data:", err);
            }
        }

        // Helper to load all manual tab data
        function loadManualTabData() {
            fetchSuppliers();
            fetchManualProducts();
        }

        // Load all data
        function loadAllData() {
            fetchStats();
            fetchWebhooks();
            fetchAlerts();
            fetchCatalog();
            loadManualTabData();
            loadAnalyticsTabData();
        }

        // Initialize on load
        window.onload = function() {
            loadAllData();
            setInterval(fetchStats, 10000);
            setInterval(fetchWebhooks, 15000);
        };
    </script>
</body>
</html>
"""
    return html_content
