import logging
import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.db.session import get_db
from app.db.models import Supplier, ManualProduct, SystemConfig, ManualSale

logger = logging.getLogger(__name__)
router = APIRouter()

# --- Pydantic Schemas ---

class SupplierCreate(BaseModel):
    name: str = Field(..., description="Nome do Fornecedor")
    contact: Optional[str] = Field(None, description="Informacoes de contato")

class ManualProductCreate(BaseModel):
    barcode: str = Field(..., description="Codigo de barras")
    reference: Optional[str] = Field(None, description="Referencia do item")
    description: str = Field(..., description="Descricao do item")
    quantity: int = Field(..., gt=0, description="Quantidade")
    unit_value: float = Field(..., ge=0.0, description="Valor unitario")
    discount: float = Field(0.0, ge=0.0, description="Desconto total")
    price_type: str = Field("normal", description="Tipo de preco: consignado, brinde, normal")
    category: str = Field(..., description="Categoria")
    subcategory: Optional[str] = Field(None, description="Subcategoria")
    supplier_id: str = Field(..., description="ID do Fornecedor (UUID)")

class ConfigUpdateRequest(BaseModel):
    credits: float = Field(..., ge=0.0, description="Creditos disponiveis")
    meta: float = Field(..., ge=0.0, description="Meta do painel")

class ManualProductSellRequest(BaseModel):
    quantity: int = Field(..., gt=0, description="Quantidade vendida")
    unit_price: Optional[float] = Field(None, ge=0.0, description="Preco unitario praticado na venda")

# --- Routes ---

# 1. Suppliers CRUD

@router.get("/suppliers", status_code=status.HTTP_200_OK)
async def list_suppliers(db: AsyncSession = Depends(get_db)):
    """
    Lista todos os fornecedores cadastrados.
    """
    try:
        stmt = select(Supplier).order_by(Supplier.name.asc())
        res = await db.execute(stmt)
        return res.scalars().all()
    except Exception as e:
        logger.error(f"Erro ao listar fornecedores: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao buscar fornecedores.")

@router.post("/suppliers", status_code=status.HTTP_201_CREATED)
async def create_supplier(payload: SupplierCreate, db: AsyncSession = Depends(get_db)):
    """
    Cadastra um novo fornecedor.
    """
    name_clean = payload.name.strip()
    if not name_clean:
        raise HTTPException(status_code=400, detail="O nome do fornecedor nao pode ser vazio.")
    
    try:
        db_supplier = Supplier(name=name_clean, contact=payload.contact)
        db.add(db_supplier)
        await db.commit()
        await db.refresh(db_supplier)
        return db_supplier
    except Exception as e:
        logger.error(f"Erro ao criar fornecedor: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao cadastrar fornecedor.")


# 2. Manual Products CRUD

@router.get("", status_code=status.HTTP_200_OK)
async def list_manual_products(db: AsyncSession = Depends(get_db)):
    """
    Lista todos os produtos cadastrados manualmente com o nome do fornecedor associado.
    """
    try:
        stmt = (
            select(ManualProduct, Supplier.name.label("supplier_name"))
            .join(Supplier, ManualProduct.supplier_id == Supplier.id, isouter=True)
            .order_by(ManualProduct.created_at.desc())
        )
        res = await db.execute(stmt)
        rows = res.all()
        
        return [
            {
                "id": str(r.ManualProduct.id),
                "barcode": r.ManualProduct.barcode,
                "reference": r.ManualProduct.reference or "",
                "description": r.ManualProduct.description,
                "quantity": r.ManualProduct.quantity,
                "unit_value": r.ManualProduct.unit_value,
                "discount": r.ManualProduct.discount,
                "total_value": r.ManualProduct.total_value,
                "price_type": r.ManualProduct.price_type,
                "category": r.ManualProduct.category,
                "subcategory": r.ManualProduct.subcategory or "",
                "supplier_id": str(r.ManualProduct.supplier_id),
                "supplier_name": r.supplier_name or "Desconhecido",
                "created_at": r.ManualProduct.created_at.isoformat()
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Erro ao listar produtos manuais: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao buscar produtos.")

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_manual_product(payload: ManualProductCreate, db: AsyncSession = Depends(get_db)):
    """
    Cadastra um novo produto manual, calculando os totais com base nas regras de preco.
    """
    try:
        # Validate supplier existence
        supplier_uuid = uuid.UUID(payload.supplier_id)
        sup_stmt = select(Supplier).where(Supplier.id == supplier_uuid)
        sup_res = await db.execute(sup_stmt)
        if not sup_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Fornecedor nao encontrado.")
            
        # Calculation logic
        price_type_clean = payload.price_type.strip().lower()
        if price_type_clean == "brinde":
            unit_val = 0.0
            disc = 0.0
            tot_val = 0.0
        else:
            unit_val = payload.unit_value
            disc = payload.discount
            tot_val = (payload.quantity * unit_val) - disc
            if tot_val < 0.0:
                tot_val = 0.0
                
        db_product = ManualProduct(
            barcode=payload.barcode.strip(),
            reference=payload.reference.strip() if payload.reference else None,
            description=payload.description.strip(),
            quantity=payload.quantity,
            unit_value=unit_val,
            discount=disc,
            total_value=tot_val,
            price_type=price_type_clean,
            category=payload.category.strip(),
            subcategory=payload.subcategory.strip() if payload.subcategory else None,
            supplier_id=supplier_uuid
        )
        
        db.add(db_product)
        await db.commit()
        await db.refresh(db_product)
        return db_product
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao cadastrar produto manual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao cadastrar produto: {str(e)}")

@router.delete("/{product_id}", status_code=status.HTTP_200_OK)
async def delete_manual_product(product_id: str, db: AsyncSession = Depends(get_db)):
    """
    Remove um produto manual cadastrado.
    """
    try:
        prod_uuid = uuid.UUID(product_id)
        stmt = delete(ManualProduct).where(ManualProduct.id == prod_uuid)
        res = await db.execute(stmt)
        await db.commit()
        
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Produto nao encontrado.")
            
        return {"status": "success", "message": "Produto removido com sucesso."}
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de produto invalido.")
    except Exception as e:
        logger.error(f"Erro ao remover produto: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao remover produto.")


# 3. Product Sales

@router.post("/{product_id}/sell", status_code=status.HTTP_200_OK)
async def sell_manual_product(product_id: str, payload: ManualProductSellRequest, db: AsyncSession = Depends(get_db)):
    """
    Registra a venda de uma determinada quantidade de um item, dando baixa no estoque local.
    """
    try:
        prod_uuid = uuid.UUID(product_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de produto invalido.")
        
    try:
        # Fetch product
        stmt = select(ManualProduct).where(ManualProduct.id == prod_uuid)
        res = await db.execute(stmt)
        product = res.scalar_one_or_none()
        
        if not product:
            raise HTTPException(status_code=404, detail="Produto nao encontrado no estoque.")
            
        if product.quantity < payload.quantity:
            raise HTTPException(
                status_code=400, 
                detail=f"Estoque insuficiente. Estoque disponivel para venda: {product.quantity}"
            )
            
        # Deduct quantity
        product.quantity -= payload.quantity
        
        # Recalculate total value
        if product.price_type == "brinde":
            product.total_value = 0.0
        else:
            tot = (product.quantity * product.unit_value) - product.discount
            product.total_value = tot if tot > 0.0 else 0.0
            
        # Register Sale
        sold_price = payload.unit_price if payload.unit_price is not None else product.unit_value
        sale_total = payload.quantity * sold_price
        
        db_sale = ManualSale(
            product_id=prod_uuid,
            quantity=payload.quantity,
            unit_price=sold_price,
            total_value=sale_total
        )
        
        db.add(db_sale)
        await db.commit()
        await db.refresh(product)
        
        return {
            "status": "success",
            "message": f"Baixa concluida: {payload.quantity} unidades de '{product.description}' vendidas por R$ {sale_total:.2f}.",
            "remaining_stock": product.quantity
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao processar venda: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao registrar venda.")

@router.get("/sales", status_code=status.HTTP_200_OK)
async def list_sales(db: AsyncSession = Depends(get_db)):
    """
    Lista o historico das ultimas 50 vendas registradas.
    """
    try:
        stmt = (
            select(ManualSale, ManualProduct.description.label("product_description"))
            .join(ManualProduct, ManualSale.product_id == ManualProduct.id, isouter=True)
            .order_by(ManualSale.sold_at.desc())
            .limit(50)
        )
        res = await db.execute(stmt)
        rows = res.all()
        return [
            {
                "id": str(r.ManualSale.id),
                "product_id": str(r.ManualSale.product_id),
                "product_description": r.product_description or "Produto Removido",
                "quantity": r.ManualSale.quantity,
                "unit_price": r.ManualSale.unit_price,
                "total_value": r.ManualSale.total_value,
                "sold_at": r.ManualSale.sold_at.isoformat()
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Erro ao listar vendas: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro ao buscar historico de vendas.")


# 4. System Configuration (Credits and Goals)

@router.get("/config", status_code=status.HTTP_200_OK)
async def get_system_config(db: AsyncSession = Depends(get_db)):
    """
    Retorna as metas e creditos salvos.
    """
    try:
        stmt = select(SystemConfig)
        res = await db.execute(stmt)
        configs = res.scalars().all()
        config_dict = {c.key: c.value for c in configs}
        return {
            "credits": config_dict.get("credits", 0.0),
            "meta": config_dict.get("meta", 0.0)
        }
    except Exception as e:
        logger.error(f"Erro ao buscar configuracoes: {str(e)}")
        return {"credits": 0.0, "meta": 0.0}

@router.post("/config", status_code=status.HTTP_200_OK)
async def update_system_config(payload: ConfigUpdateRequest, db: AsyncSession = Depends(get_db)):
    """
    Atualiza as metas e os creditos disponiveis.
    """
    try:
        # Update credits
        cred_stmt = select(SystemConfig).where(SystemConfig.key == "credits")
        cred_res = await db.execute(cred_stmt)
        cred_cfg = cred_res.scalar_one_or_none()
        if not cred_cfg:
            cred_cfg = SystemConfig(key="credits", value=payload.credits)
            db.add(cred_cfg)
        else:
            cred_cfg.value = payload.credits

        # Update meta
        meta_stmt = select(SystemConfig).where(SystemConfig.key == "meta")
        meta_res = await db.execute(meta_stmt)
        meta_cfg = meta_res.scalar_one_or_none()
        if not meta_cfg:
            meta_cfg = SystemConfig(key="meta", value=payload.meta)
            db.add(meta_cfg)
        else:
            meta_cfg.value = payload.meta

        await db.commit()
        return {"status": "success", "credits": payload.credits, "meta": payload.meta}
    except Exception as e:
        logger.error(f"Erro ao atualizar configuracoes: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro ao salvar configuracoes.")


# 5. Dashboard Analytics for Manual Products

@router.get("/analytics", status_code=status.HTTP_200_OK)
async def get_manual_analytics(db: AsyncSession = Depends(get_db)):
    """
    Executa calculos de aggregacao sobre o estoque manual e vendas, retornando os KPIs do Dashboard.
    """
    try:
        # Fetch all manual products
        stmt = select(ManualProduct)
        res = await db.execute(stmt)
        products = res.scalars().all()
        
        # Fetch all sales
        sales_stmt = select(ManualSale)
        sales_res = await db.execute(sales_stmt)
        sales = sales_res.scalars().all()
        
        # Fetch config (credits and meta)
        cfg_stmt = select(SystemConfig)
        cfg_res = await db.execute(cfg_stmt)
        config_dict = {c.key: c.value for c in cfg_res.scalars().all()}
        credits = config_dict.get("credits", 0.0)
        meta = config_dict.get("meta", 0.0)
        
        # KPI Aggregates for Inventory
        total_quantity = 0
        total_value = 0.0
        total_discount = 0.0
        
        # KPI Aggregates for Sales
        total_sales_value = sum(s.total_value for s in sales)
        total_sales_quantity = sum(s.quantity for s in sales)
        
        # Categorized metrics maps
        qty_by_cat = {}
        val_by_cat = {}
        
        qty_by_subcat = {}
        val_by_subcat = {}
        
        qty_by_type = {}
        val_by_type = {}
        
        for p in products:
            total_quantity += p.quantity
            total_value += p.total_value
            total_discount += p.discount
            
            # Category grouping
            cat = p.category.strip() or "Sem Categoria"
            qty_by_cat[cat] = qty_by_cat.get(cat, 0) + p.quantity
            val_by_cat[cat] = val_by_cat.get(cat, 0.0) + p.total_value
            
            # Subcategory grouping
            sub = p.subcategory.strip() if p.subcategory else "Sem Subcategoria"
            qty_by_subcat[sub] = qty_by_subcat.get(sub, 0) + p.quantity
            val_by_subcat[sub] = val_by_subcat.get(sub, 0.0) + p.total_value
            
            # Price Type grouping
            ptype = p.price_type.strip().lower() or "normal"
            qty_by_type[ptype] = qty_by_type.get(ptype, 0) + p.quantity
            val_by_type[ptype] = val_by_type.get(ptype, 0.0) + p.total_value

        # Calculate sales target progress (Total Revenue / Meta)
        meta_progress = (total_sales_value / meta * 100.0) if meta > 0.0 else 0.0
        
        # Format breakdown lists for the frontend
        category_breakdown = [
            {"category": k, "quantity": qty_by_cat[k], "total_value": val_by_cat[k]}
            for k in qty_by_cat
        ]
        subcategory_breakdown = [
            {"subcategory": k, "quantity": qty_by_subcat[k], "total_value": val_by_subcat[k]}
            for k in qty_by_subcat
        ]
        type_breakdown = [
            {"price_type": k, "quantity": qty_by_type[k], "total_value": val_by_type[k]}
            for k in qty_by_type
        ]

        return {
            "summary": {
                "total_quantity": total_quantity,
                "total_value": total_value,
                "total_discount": total_discount,
                "credits": credits,
                "meta": meta,
                "total_sales_value": total_sales_value,
                "total_sales_quantity": total_sales_quantity,
                "meta_progress_percentage": round(meta_progress, 2)
            },
            "by_category": category_breakdown,
            "by_subcategory": subcategory_breakdown,
            "by_price_type": type_breakdown
        }
        
    except Exception as e:
        logger.error(f"Erro no calculo analitico: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno no processamento analitico.")
