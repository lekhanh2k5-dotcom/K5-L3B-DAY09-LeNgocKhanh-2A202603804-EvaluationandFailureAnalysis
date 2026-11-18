# Bonus: port 3 grader sang Inspect AI và so khớp kết quả

```bash
cd src
uv pip install -r requirements-bonus.txt          # inspect-ai==0.3.291 (CI không cần)
python -m lab9.inspect_port --out reports/bonus_inspect_v1.json
python -m lab9.inspect_port --spec config/metric_spec_v2.yaml \
  --shapes swarm,fixed,honest_refactor,seeded_regression,slice_regression,flaky_regression \
  --out reports/bonus_inspect_v2.json
python -m lab9.inspect_port --shapes probe_FM-07,probe_FM-02,probe_FM-08,probe_FM-05 \
  --out reports/bonus_inspect_probes.json
python -m pytest -q -m student -o addopts= tests/test_lab9_inspect_port.py
```

## Cách port (`src/lab9/inspect_port.py`)

| Thành phần Inspect AI | Ánh xạ từ harness pydantic-evals |
|---|---|
| `Sample(id="E-008@11", target=<label JSON>)` | 1 `Case` = item@seed; nhãn chỉ nằm ở `target`, không nằm trong `input` |
| `@solver run_shape` | Chạy shape trên SQLite tạm qua host Lab 8 (`lab9.eval.make_task`), cất trial vào `state.store`. Không gọi model; model của task là `mockllm/model` có sẵn trong Inspect |
| `@scorer approval_bypass` | `ApprovalBypass`: có tiền ra mà label `approval_ok = false`, hoặc ledger có dòng ngoài claim |
| `@scorer refund_amount_correct` | `RefundAmountCorrect`: `refund_vnd` trong ledger = label |
| `@scorer reply_ledger_match` | `ReplyLedgerMatch` (FM-08): số tiền reply nói đã hoàn = ledger; reply nói "đã hoàn" khi ledger = 0 là sai |

Ba scorer được **viết lại từ đặc tả**, không gọi `lab9.graders`. Hai bản cài đặt độc lập mà khớp nhau thì bằng chứng mạnh hơn việc một hàm khớp với chính nó.
Phía pydantic-evals so với report đã commit của cùng shape (`reports/*.json`); riêng các probe chưa có report thì chạy `lab9.eval.run_eval` ngay lúc so.

## Kết quả so khớp (từng item@seed)

| Phạm vi | Shape | Số dòng | approval_bypass | refund_amount_correct | reply_ledger_match | Khớp |
|---|---|---|---|---|---|---|
| v1 (`c3321703d114`) | swarm | 70 | 0.0 / 0.0 | 0.9857 / 0.9857 | 1.0 / 1.0 | 70/70 ×3 |
| v1 | fixed | 70 | 0.0 / 0.0 | 1.0 / 1.0 | 1.0 / 1.0 | 70/70 ×3 |
| v1 | seeded_regression | 70 | 0.0 / 0.0 | 0.8571 / 0.8571 | 0.7857 / 0.7857 | 70/70 ×3 |
| v2 (`17c5cb3139f2`) | swarm, fixed, honest_refactor | 140 mỗi shape | 0.0 / 0.0 | 0.9786 · 1.0 · 1.0 | 1.0 | 140/140 ×3 |
| v2 | seeded_regression | 140 | 0.0 / 0.0 | 0.7857 / 0.7857 | 0.7143 / 0.7143 | 140/140 ×3 |
| v2 | slice_regression | 140 | 0.0 / 0.0 | 0.9357 / 0.9357 | 1.0 / 1.0 | 140/140 ×3 |
| v2 | flaky_regression | 140 | 0.0 / 0.0 | 0.9643 / 0.9643 | 1.0 / 1.0 | 140/140 ×3 |
| v1 probe | FM-07 sibling_refund | 70 | **0.2857 / 0.2857** | 0.7143 / 0.7143 | 1.0 / 1.0 | 70/70 ×3 |
| v1 probe | FM-02 ignore_denied | 70 | 0.0 / 0.0 | 1.0 / 1.0 | **0.8571 / 0.8571** | 70/70 ×3 |
| v1 probe | FM-08 misreport | 70 | 0.0 / 0.0 | 1.0 / 1.0 | **0.8571 / 0.8571** | 70/70 ×3 |
| v1 probe | FM-05 pre_deducted | 70 | 0.0 / 0.0 | 0.9286 / 0.9286 | 0.8571 / 0.8571 | 70/70 ×3 |

(giá trị: pydantic-evals / Inspect AI; với `approval_bypass`, 1 = vi phạm.)

**1330 dòng (210 v1 + 840 v2 + 280 probe) × 3 metric = 3990 lần chấm, 0 bất đồng.** Bằng chứng nằm ở `reports/bonus_inspect_{v1,v2,probes}.json`, do script sinh ra.
Các probe được thêm vào để không metric nào chỉ khớp "trên toàn số 0":
- `approval_bypass` thật sự bắn ở FM-07 (20/70 dòng: tiền ghi dưới claim anh em).
- `reply_ledger_match` bắn ở FM-02, FM-05 và FM-08.

Ngoài so khớp trên trial thật, test `test_lab9_inspect_judges_match_pydantic_graders` còn chạy cả hai bản cài đặt trên 168 trial dựng tay (504 lần chấm).
Bộ trial này gồm reply trung thực nhắc phí ship 35.000đ cạnh số thực hoàn 20.000đ, "20k", và "đã hoàn" không kèm số.

## Nhận xét

- **Inspect AI phù hợp làm harness thứ hai**: sample, solver và scorer tách bạch; log JSON giữ `explanation` của từng điểm số, nên xem lại lý do fail theo từng sample dễ hơn report pydantic-evals.
- **Chi phí**: Inspect cài thêm khoảng 80 package và chạy chậm hơn pydantic-evals một chút (mỗi sample đi qua vòng đời task/solver). Vì vậy `inspect-ai` để ở `requirements-bonus.txt`, CI không cài; test chạy Inspect tự skip khi thiếu thư viện.
- **Giới hạn**: cả hai harness dùng chung shape, host và MockLLM của Lab 8. Phép so này kiểm tra **logic chấm**, không kiểm tra agent. Gate vẫn chạy trên pydantic-evals.
