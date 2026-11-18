# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case của tôi: `seeded_regression C-008@11` (FM-08)

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-008 --seed 11
python -m lab9.trace_case --shape fixed --claim C-008 --seed 11
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-008@11`, row `E-008@11` trong report `E-seeded_regression-20261118-81ae` (`reports/eval_seeded_regression.json`) |
| Triệu chứng | Grader Lab 8 **PASS** (`ok`) và `refund_amount_correct` cũng pass vì ledger 20.000 = label 20.000. Chỉ `reply_ledger_match` fail: reply nói **"Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."** nhưng ledger chỉ có **20.000đ**. Khách được hứa nhiều hơn 15.000đ so với số thực nhận. |
| Bước sai đầu tiên | **Event 5 `reply`**: `{"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."}` |
| Vì sao là bước *đầu tiên* | Ev1 `handoff` đúng allowlist; ev2 `investigator` đọc O-808 `delay_days: 4` từ DB, không có override; ev3 `quote` 35.000 (`SHIP-LATE-03`), đúng `proposal_amount` của label; ev4 `refund_history` 0/0, đúng vì đơn chưa từng hoàn. Host ghi 20.000 do trần approval A-008 (`approved_vnd: 20000`). Đây là quyết định đúng của host, không phải của agent. Agent sai ở ev5: báo lại số mình đề xuất, không phải số host đã ghi (`effect.amount_vnd`). |
| Failure mode | **FM-08** misreport (`docs/failure_taxonomy.md`). Công tắc gây ra là `pre_deducted`: variant agent báo `proposal` thay vì `committed` khi công tắc này bật. Lỗi quan sát được trên trace là FM-08. |
| Đối chứng | `fixed C-008@11`: ev1–ev3 giống hệt, không có ev4 `refund_history`, ev4 `reply` "Dạ, LogiX đã hoàn **20.000đ** cho đơn O-808.". Reply lấy đúng số host đã ghi. |
| Regression test | `tests/test_lab9_trace_case.py::test_lab9_trace_case_c008_misreport_is_caught`: assert grader Lab 8 PASS, ledger 20.000, `reply` ở event 5, `ReplyLedgerMatch` = False với lý do chứa `35000`. Đối chứng `test_lab9_trace_case_c008_fixed_control_passes` pass trên `fixed`. Đã chạy: fail trên variant lỗi, pass trên `fixed` (3 passed). Ở mức eval set: metric `reply_ledger_match` (blocking, min 1.0) chặn `seeded_regression` với Δ −0.214, CI [−0.429, +0.000]. |
| Chưa chắc chắn | Trace không có event cho kết quả `issue_refund` của host, nên con số 20.000 chỉ đọc được từ ledger. Không thấy trên trace host đã cắt số tiền vì lý do gì; lý do trần approval là suy ra từ world state. Reply của Lab 8 `swarm` không có event `reply`, nên metric này không áp dụng được cho baseline swarm: nó coi "không nói gì" là đúng. |

Case phụ (cùng file test): `seeded_regression C-002@11`, FM-03. Bước sai đầu tiên là ev3 `model_override {"delay_days": 5}` (DB = 2); test `test_lab9_trace_case_c002_ticket_override_is_caught` xác nhận `DbFactKept` = False.

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
