from hitl import ApprovalRequest, hitl_gate

req = ApprovalRequest(
    run_id="test-001",
    reason="Risk score 0.82 exceeds threshold 0.70",
    risk_score=0.82,
    risk_level="Critical",
    summary_headline="Acme Corp faces regulatory headwinds after record earnings",
)

approved = hitl_gate(req)
print(f"Gate returned: {approved}")