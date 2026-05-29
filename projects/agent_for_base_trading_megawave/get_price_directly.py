from get_token_balance_and_price import get_neipan_token_price
from get_token_balance_and_price import get_waipan_token_price
from get_virtual_pool_address import get_virtual_pool_address_neipan
from get_virtual_pool_address import get_virtual_pool_address_waipan
from get_debank_token_info import get_token_price
POOL_DICT_neipan = {}
POOL_DICT_waipan = {}
def get_price_directly( token_address: str) -> float:
    """获取代币当前价格"""
    # 这里实现你的价格获取逻辑
    # 示例实现，实际使用时需要替换成真实的价格获取逻辑
    #print(f"获取价格: {token_address}")
    #print(f"POOL_DICT: {POOL_DICT}")
    token_symple,token_name=get_token_price(
        token_address=token_address,
    )
    if token_name.startswith("fun"):
        print(f"获取价格1")
        if token_address not in POOL_DICT_neipan:
            print(f"获取虚拟池地址: {token_address}")
            POOL_DICT_neipan[token_address] = get_virtual_pool_address_neipan(token_address)
        pool_address = POOL_DICT_neipan[token_address]
        #print(f"pool_address: {pool_address}")
        try:
            pool_token_price_by_usd, pool_token_price_by_virtual, virtual_price , price_change_percent= get_neipan_token_price(pool_address)
        except Exception as e:
            print(f"获取价格失败: {str(e)}")
            return None, None, None, None,None
        mark_cap=pool_token_price_by_usd*1000000000/10000
        return   pool_token_price_by_usd, pool_token_price_by_virtual, virtual_price , price_change_percent,mark_cap
    else:
        print(f"获取价格2")
        if token_address not in POOL_DICT_waipan:
            print(f"获取虚拟池地址: {token_address}")
            POOL_DICT_waipan[token_address] = get_virtual_pool_address_waipan(token_address)
        pool_address = POOL_DICT_waipan[token_address]
        #print(f"pool_address: {pool_address}")
        try:
            pool_token_price_by_usd, pool_token_price_by_virtual, virtual_price , price_change_percent= get_waipan_token_price(pool_address,token_address)
        except Exception as e:
            print(f"获取价格失败: {str(e)}")
            return None, None, None, None,None
        mark_cap=pool_token_price_by_usd*1000000000/10000
        return   pool_token_price_by_usd, pool_token_price_by_virtual, virtual_price , price_change_percent,mark_cap
a=2
if a==1:
    a=get_price_directly("0x06ABb84958029468574B28b6e7792A770CcaA2F6")
    print(a)

