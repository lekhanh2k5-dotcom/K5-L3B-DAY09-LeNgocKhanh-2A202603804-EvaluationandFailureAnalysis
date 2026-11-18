# Judge audit

Chạy (trong `src/`): `python -m lab9.judge --csv <file> --audit 5`. Judge chạy ở chế độ replay
(verdict lưu sẵn trong CSV), FAIL là lớp dương vì việc của judge là **tìm lỗi**.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (exit 0) | **dùng**, không blocking: tone là chất lượng, không phải an toàn |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (exit 1) | **loại**, không dùng làm gate |

Ma trận nhầm lẫn (FAIL = dương):

| Tiêu chí | TP | FP | FN | TN | Specificity | Tỉ lệ FAIL quan sát | Rogan-Gladen | Tỉ lệ FAIL theo người |
|---|---|---|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.943 | 0.28 | **0.30** | 0.30 |
| helpful | 9 | 0 | 21 | 70 | 1.000 | 0.09 | **0.30** | 0.30 |

Rogan-Gladen kéo cả hai về đúng tỉ lệ thật 0.30. Nhưng với helpful, hiệu chỉnh từ 0.09 lên 0.30 gấp hơn 3 lần.
Con số hiệu chỉnh khi đó gần như hoàn toàn do ước lượng sensitivity (0.3) quyết định, và chỉ dựa trên 30 mẫu FAIL.
Hiệu chỉnh như vậy quá mong manh để dùng làm sàn cho gate.

## Audit thủ công: 10 bất đồng của tone_ok + phân loại 21 FN của helpful

### tone_ok

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú → sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | **Người** | Xưng "em" + "nha" quá suồng sã. Rubric: bắt buộc xưng "anh/chị", gọi mình là "LogiX"; cấm "em/bạn/nha/nhé". Thêm H-008 làm few-shot FAIL. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…rồi nha" | PASS | FAIL | **Người** | Cùng lỗi xưng hô; judge nhầm thân mật với thân thiện. Cùng quy tắc với #1. |
| 3 | H-029 "Dạ, vui lòng chờ…không cần nhắn thêm." | PASS | FAIL | **Người** | Judge bị từ lịch sự đầu câu đánh lừa. Rubric: câu ra lệnh hoặc gạt khách ("không cần nhắn thêm") là FAIL, dù có "Dạ/vui lòng". |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". Rubric: bỏ yêu cầu bắt buộc xin lỗi khi reply đã giải quyết xong và lịch sự. |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | **Người** | "refund" nằm trong danh sách từ được CS LogiX cho phép. Rubric: đưa whitelist thuật ngữ vào prompt. |
| 6 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | **Người**, nhưng sai tiêu chí | Lỗi là hứa khoản tiền ngoài kết quả hệ thống, thuộc về nội dung chứ không phải tone. Rubric tone: không chấm cam kết tiền. Chuyển sang code grader `reply_ledger_match` (FM-08). |
| 7 | H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người** | Rubric: emoji trong ngữ cảnh khiếu nại là FAIL. |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…ạ." | FAIL | PASS | **Judge** | Ghi chú dữ liệu: người đọc nhầm ticket. Hành động: sửa nhãn người thành FAIL trong bộ nhãn kế tiếp. Không sửa CSV công khai, vì test đang tham chiếu số liệu của nó. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ…" | FAIL | PASS | **Người** | Lặp từ do gõ phím, không phải giọng điệu. Rubric: lỗi gõ nhỏ không làm FAIL tone. |
| 10 | H-094 "Da, LogiX da hoan 40.000đ…xin loi…" | PASS | FAIL | **Người** | Mất dấu tiếng Việt (dịch máy) là thiếu tôn trọng khách. Rubric: reply không dấu là FAIL. |

Nếu sửa nhãn H-081 (#8), số liệu tone thành TP 25, FP 3, FN 6, TN 66: κ = 0.784, P = 0.893, R = 0.806, vẫn đạt sàn.
6 FN của judge tone gồm 3 lỗi xưng hô / giọng ra lệnh (H-008, H-017, H-029), 1 emoji, 1 mất dấu và 1 hứa tiền (lỗi này nằm ngoài phạm vi tone).
Sửa rubric #1–#3 xử lý được nhóm lớn nhất. 4 FP đều do judge quá khắt khe (xin lỗi, "refund", lỗi gõ), trừ H-081 là judge đúng.

### helpful (21 FN, 0 FP)

| Nhóm | Số case | Ví dụ | Vì sao judge sai |
|---|---|---|---|
| Reply nói số tiền khác ledger | 18 | HL-015 "đã hoàn 55.000đ" (ledger 40.000đ); HL-020 "90.000đ" (ledger 120.000đ); HL-016, HL-098 thêm 2–3 câu xin lỗi | Judge chỉ đọc reply, **không thấy ledger**, nên không thể biết số sai. Reply dài và nhiều lời xin lỗi còn khiến judge chấm PASS (thiên vị độ dài, độ lịch sự). |
| Trả lời mơ hồ, không có số tiền | 3 | HL-047, HL-091, HL-097 "Ok bạn, đơn O-xxx xử lý rồi nhé." | Khách không biết đã được hoàn bao nhiêu; judge coi "xử lý rồi" là đủ. |

Judge helpful chỉ bắt được các reply rỗng hoặc từ chối trần (9 TP: "Bạn gửi lại thông tin đi.", "Đơn O-909 không được hoàn.").
P = 1.0 nhìn thì đẹp, nhưng đó là vì judge hầu như không bao giờ nói FAIL.

## Kết luận

- **helpful bị loại** (κ 0.375 < 0.6, R 0.30 < 0.7). Ma trận nhầm lẫn cho thấy judge bỏ sót 21/30 reply hỏng (FN = 21), trong khi FP = 0. Nếu dùng làm gate, nó sẽ cho qua 70% lỗi và báo tỉ lệ lỗi 0.09 thay vì 0.30. 18/21 FN là lỗi **số tiền sai so với ledger**, mà theo quy tắc thì tiền luôn chấm bằng code. Hành động: thay phần "đúng số tiền" bằng metric code `reply_ledger_match` (M3, FM-08). Rubric helpful còn lại chỉ chấm "có nêu kết quả + số tiền + bước tiếp theo", và phải hiệu chỉnh lại trên nhãn mới trước khi dùng.
- **tone_ok dùng được** nhưng chỉ ở mức theo dõi, không blocking. Áp 7 sửa đổi rubric ở trên (xưng hô, câu ra lệnh, không bắt buộc xin lỗi, whitelist "refund", emoji, mất dấu, bỏ qua lỗi gõ) rồi hiệu chỉnh lại.
- **Rủi ro còn lại**:
  - Judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí), lại chính là dữ liệu dùng để sửa rubric. Cần một bộ nhãn người mới làm held-out thật.
  - Mỗi tiêu chí chỉ có 30 mẫu FAIL, nên khoảng tin cậy của recall còn rộng.
  - Nhãn người cũng sai (H-081), nên cần người thứ hai gán nhãn để đo κ giữa người với người.
