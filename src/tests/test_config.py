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
        ("899050.BJ", "index_daily"),   # 北证50指数
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


def test_role_default_and_validate():
    """role 默认 target；非法 role 校验抛错；observe 合法。"""
    idx = config_mod.IndexConfig(name="x", ts_code="000300.SH")
    assert idx.role == "target" and idx.is_target is True
    obs = config_mod.IndexConfig(name="金", ts_code="AU9999", role="observe")
    assert obs.is_target is False
    obs.validate()  # 合法
    bad = config_mod.IndexConfig(name="x", ts_code="000300.SH", role="bogus")
    raised = False
    try:
        bad.validate()
    except config_mod.ConfigError:
        raised = True
    assert raised
    print("PASS test_role_default_and_validate")


def test_indices_json_roles():
    """项目 indices.json：六个目标标的为 target，国债ETF/黄金为 observe。"""
    indices = config_mod.Config._load_indices(None, None)
    by_name = {i.name: i for i in indices}
    for nm in ("沪深300", "科创50", "创业板50", "恒生科技", "北证50", "港股创新药ETF"):
        assert by_name[nm].role == "target", nm
    for nm in ("十年期国债ETF", "黄金9999"):
        assert by_name[nm].role == "observe", nm
    print("PASS test_indices_json_roles")


def test_bull_strategy_defaults():
    """生产默认牛市参数：EMA周期=50、价格缓冲=0.00、斜率回看=12。"""
    assert config_mod.BULL_EMA_WEEKS == 50
    assert config_mod.BULL_CLOSE_BUFFER == 0.00
    assert config_mod.BULL_SLOPE_LOOKBACK_WEEKS == 12
    print("PASS test_bull_strategy_defaults")


if __name__ == "__main__":
    test_infer_api_by_ts_code()
    test_explicit_api_wins()
    test_invalid_api_raises()
    test_role_default_and_validate()
    test_indices_json_roles()
    test_bull_strategy_defaults()
    print("test_config OK")
