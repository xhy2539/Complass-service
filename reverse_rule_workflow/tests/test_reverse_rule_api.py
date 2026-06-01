from fastapi.testclient import TestClient

from app.main import app


def test_extract_reverse_rules_endpoint_returns_candidate_rules():
    client = TestClient(app)

    response = client.post(
        "/reverse-rule/extract",
        json=[
            {
                "pair_id": "pair-1",
                "before_text": "甲方应在验收后90日内向乙方支付服务费。",
                "after_text": "甲方应在验收并收到合法有效发票后30日内向乙方支付服务费。",
                "contract_type": "服务合同",
                "review_role": "乙方",
            }
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]
    assert isinstance(payload["rules"], list)
