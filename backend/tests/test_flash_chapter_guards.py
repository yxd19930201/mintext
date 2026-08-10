from app.services.ai_service import _audit_focus_rules
from app.services.novel_generate_service import _local_chapter_issues


def issue_types(content: str, synopsis: str, time_place: str = "1993年深圳"):
    return {
        item["type"]
        for item in _local_chapter_issues(
            content,
            {"synopsis": synopsis},
            {"time_place": time_place},
        )
    }


def test_rejects_meta_leak_and_real_trading_in_simulation_only_outline():
    content = (
        "正文" * 1300
        + "大纲要求本章达到二十万元。"
        + "他打开实盘账户，用现实资金买入股票，随后登上实盘榜。"
    )
    types = issue_types(
        content,
        "初赛只使用模拟资金，现实资金不参与，现实现金保持135500元。",
    )
    assert "meta_leak" in types
    assert "simulation_real_money_conflict" in types
    assert "competition_rule_conflict" in types


def test_rejects_anachronistic_short_selling_and_device():
    content = (
        "正文" * 1300
        + "他让证券公司借券做空。小灵通响了，原来是旅社前台的电话打上来的。"
    )
    types = issue_types(content, "进入下一轮交易。")
    assert "historical_market_rule" in types
    assert "historical_device" in types


def test_rejects_same_day_suspension_and_resumption():
    content = "正文" * 1300 + "公告称下周一停牌一天。周一上午九点半，股票复牌。"
    assert "timeline_conflict" in issue_types(content, "股票公告后复牌。")


def test_rejects_premature_title_and_conflicting_delivery_terms():
    content = (
        "正文" * 1300
        + "三人签订五千元周转协议，但专用端子厂里没库存，明天再去深圳找料。"
        + "他在账本写下：五千元已经转为有货权保障的周转资产。"
        + "他先说交期从原料到厂后起算，随后又让人带话，承诺十天交期，逾期一天才亲自验货。"
    )
    types = issue_types(content, "预留不超过5000元周转额度，采购后才形成货权。")
    assert "premature_asset_recognition" in types
    assert "delivery_term_conflict" in types
    assert "invalid_delivery_liability" in types


def test_rejects_relaxed_receivable_collection():
    content = (
        "正文" * 1300
        + "做成新订单，贸易部十二万元应收款不用急着催。"
    )
    types = issue_types(content, "继续按账龄催收旧应收款。")
    assert "receivable_collection_regression" in types


def test_audit_modules_are_selected_by_chapter_subject():
    business = _audit_focus_rules({
        "chapter_outline": {"synopsis": "客户确认订单，采购材料后生产交付并回款。"},
        "candidate_content": "工厂收到定金。",
    })
    assert "【通用事件状态机】" in business
    assert "【资金与资产】" in business
    assert "【合同与经营】" in business
    assert "【生产制造】" in business
    assert "【证券交易】" not in business

    securities = _audit_focus_rules({
        "chapter_outline": {"synopsis": "使用证券模拟账户买入股票。"},
        "candidate_content": "比赛统一本金五万元。",
    })
    assert "【证券交易】" in securities
    assert "【合同与经营】" not in securities
