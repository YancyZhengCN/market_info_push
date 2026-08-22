"""IndexConfig api 自动推断测试：留空按 ts_code 推断，显式指定则优先。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as config_mod


def test_infer_api_by_ts_code():
    """不填 api 时，按 ts_code 后缀/格式推断接口类型。"""
    cases = [
        ("000300.SH", "index_daily"),   # A股指数
        ("399673.SZ", "index_daily"),   # 深市指数
        ("511260.SH", "index_daily"),   # ETF 与 A股指数同走腾讯前复权
        ("931787.CSI", "index_csi"),    # 中证指数
        ("HKTECH", "index_global"),     # 港股指数（非数字代码）
        ("AU9999", "spot_sge"),         # 黄金现货（上海金交所）
    ]
    for ts_code, expected in cases:
        idx = config_mod.IndexConfig(name="x", ts_code=ts_code)
        assert idx.api == expected, f"{ts_code} 推断应为 {expected}，实际 {idx.api}"
    print("PASS test_infer_api_by_ts_code")


def test_explicit_api_wins():
    """显式指定 api 时以其为准，不做推断。"""
    idx = config_mod.IndexConfig(name="x", ts_code="511260.SH", api="fund_daily")
    assert idx.api == "fund_daily"
    idx.validate()  # 合法值不应抛错
    print("PASS test_explicit_api_wins")


def test_invalid_api_raises():
    """非法 api 校验应抛错。"""
    idx = config_mod.IndexConfig(name="x", ts_code="000300.SH", api="bogus")
    raised = False
    try:
        idx.validate()
    except config_mod.ConfigError:
        raised = True
    assert raised
    print("PASS test_invalid_api_raises")


if __name__ == "__main__":
    test_infer_api_by_ts_code()
    test_explicit_api_wins()
    test_invalid_api_raises()
    print("test_config OK")
