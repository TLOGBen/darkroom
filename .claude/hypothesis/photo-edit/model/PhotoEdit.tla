---------------------------- MODULE PhotoEdit ----------------------------
(* darkroom：一張照片的編輯、清除、取回上一份。                                   *)
(* 來源：darkroom_app/services/photo_library.py、adapters/persist/edit_store.py   *)
(* 每個動作的每一步都對到程式的一行（註解 file:line）。HTTP 請求跑在 worker thread   *)
(* （server.py:130），MCP 是另一個行程（mcp_server/__init__.py:1），兩者共用同一個   *)
(* 資料夾。現行程式（Locked = TRUE）：設定、清除、取回、貼上的「讀、比對、寫」都握著  *)
(* 編輯鎖 edits/edits.lock（edit_store.py:112-130：跨行程 locks.held＋行程內的鎖）。 *)
(* Locked = FALSE 是 4afcc58 的舊程式（沒有鎖），留作「看過它失敗」的對照組。        *)
EXTENDS Naturals

CONSTANTS Locked,     \* TRUE = 現行程式（有編輯鎖）；FALSE = 4afcc58 的舊程式（沒有鎖）
          NoRestore   \* TRUE = 拿掉「取回上一份」（看過它成功：目標應走不到）

Actors == {"app", "agent"}          \* App 的請求、AI 代理經 MCP 的請求
Edits  == {"A", "B"}                 \* 兩份不同的編輯
None   == "none"

VARIABLES cur,        \* 照片目前的編輯檔 edits/<fp>.json（edit_store.py:55-57）
          prev,       \* 留著的上一份 edits/<fp>.prev.json（edit_store.py:59-61）
          holder,     \* 誰握著編輯鎖（None = 沒人；舊程式永遠是 None）
          pc,         \* 每個請求做到哪一步
          snapCur,    \* 請求讀到的目前編輯
          snapPrev,   \* 請求讀到的上一份
          overwrote,  \* 曾經用取回蓋掉一份不同的編輯（R1 的反面）
          lost,       \* 曾經有一份編輯被清掉、卻沒留成上一份（R2 的反面）
          restored    \* 曾經成功取回上一份（目標 G1）

vars == <<cur, prev, holder, pc, snapCur, snapPrev, overwrote, lost, restored>>

Init ==
  /\ cur = None /\ prev = None /\ holder = None
  /\ pc = [a \in Actors |-> "idle"]
  /\ snapCur = [a \in Actors |-> None] /\ snapPrev = [a \in Actors |-> None]
  /\ overwrote = FALSE /\ lost = FALSE /\ restored = FALSE

Idle(a) == pc[a] = "idle"
Go(a, s) == pc' = [pc EXCEPT ![a] = s]
Release == holder' = None            \* 離開 with self.edits.locked(...)（edit_store.py:128-130）

\* 設定編輯：拿鎖、重讀、決定、整檔原子替換、放鎖（photo_library.py:335-365，鎖在 :349，
\* 寫入 :364 → edit_store.py:136）。鎖外的第一輪只檢查參數、不寫（:337-348），所以在鎖裡
\* 是一步。貼上編輯對每張目標也是同一步（photo_library.py:432-437）。舊程式沒有鎖，一樣是一步。
Set(a, e) ==
  /\ Idle(a) /\ holder = None
  /\ cur' = e
  /\ UNCHANGED <<prev, holder, pc, snapCur, snapPrev, overwrote, lost, restored>>

\* ---- 清除編輯 ----
\* 鎖外先看編輯檔在不在：不在就直接回答、什麼都不寫（photo_library.py:371-372，沒有狀態改變）
ClearCheck(a) ==                    \* photo_library.py:371  if not self.edits.exists(fp)
  /\ Locked /\ Idle(a) /\ cur /= None
  /\ Go(a, "c_check")
  /\ UNCHANGED <<cur, prev, holder, snapCur, snapPrev, overwrote, lost, restored>>
ClearLock(a) ==                     \* photo_library.py:373 → edit_store.py:117-128  拿編輯鎖
  /\ pc[a] = "c_check" /\ holder = None
  /\ holder' = a /\ Go(a, "c_locked")
  /\ UNCHANGED <<cur, prev, snapCur, snapPrev, overwrote, lost, restored>>
ClearRead(a) ==                     \* photo_library.py:374  existing = self.edits.read(...)
  /\ IF Locked THEN pc[a] = "c_locked" ELSE Idle(a)
  /\ snapCur' = [snapCur EXCEPT ![a] = cur] /\ Go(a, "c_read")
  /\ UNCHANGED <<cur, prev, holder, snapPrev, overwrote, lost, restored>>
ClearExists(a) ==                   \* edit_store.py:141  if os.path.exists(p)
  /\ pc[a] = "c_read"
  /\ IF cur = None THEN Go(a, "idle") /\ Release ELSE Go(a, "c_exists") /\ UNCHANGED holder
  /\ UNCHANGED <<cur, prev, snapCur, snapPrev, overwrote, lost, restored>>
ClearKeep(a) ==                     \* edit_store.py:143-145  write_json(prev_path, keep)
  /\ pc[a] = "c_exists"
  /\ prev' = IF snapCur[a] /= None THEN snapCur[a] ELSE prev
  /\ Go(a, "c_kept")
  /\ UNCHANGED <<cur, holder, snapCur, snapPrev, overwrote, lost, restored>>
ClearRemove(a) ==                   \* edit_store.py:147  self.folder.remove(p)；之後放鎖
  /\ pc[a] = "c_kept"
  /\ lost' = (lost \/ (cur /= None /\ cur /= snapCur[a]))
  /\ cur' = None /\ Go(a, "idle") /\ Release
  /\ UNCHANGED <<prev, snapCur, snapPrev, overwrote, restored>>

\* ---- 取回上一份 ----
\* 鎖外先看有沒有上一份：沒有就回 not_found、什麼都不寫（photo_library.py:382-384，沒有狀態改變）
RestoreCheck(a) ==                  \* photo_library.py:382  if not self.edits.has_previous(fp)
  /\ Locked /\ ~NoRestore /\ Idle(a) /\ prev /= None
  /\ Go(a, "r_check")
  /\ UNCHANGED <<cur, prev, holder, snapCur, snapPrev, overwrote, lost, restored>>
RestoreLock(a) ==                   \* photo_library.py:385 → edit_store.py:117-128  拿編輯鎖
  /\ pc[a] = "r_check" /\ holder = None
  /\ holder' = a /\ Go(a, "r_locked")
  /\ UNCHANGED <<cur, prev, snapCur, snapPrev, overwrote, lost, restored>>
RestoreRead(a) ==                   \* photo_library.py:386  current = self.edits.read(...)
  /\ IF Locked THEN pc[a] = "r_locked" ELSE ~NoRestore /\ Idle(a)
  /\ snapCur' = [snapCur EXCEPT ![a] = cur] /\ Go(a, "r_read")
  /\ UNCHANGED <<cur, prev, holder, snapPrev, overwrote, lost, restored>>
RestorePrev(a) ==                   \* photo_library.py:387-389  prev = read_previous；沒有就 not_found（放鎖）
  /\ pc[a] = "r_read"
  /\ snapPrev' = [snapPrev EXCEPT ![a] = prev]
  /\ IF prev = None THEN Go(a, "idle") /\ Release ELSE Go(a, "r_prev") /\ UNCHANGED holder
  /\ UNCHANGED <<cur, prev, snapCur, overwrote, lost, restored>>
RestoreWrite(a) ==                  \* photo_library.py:393-396  比對讀到的目前編輯，不同就 conflict，否則寫入；放鎖
  /\ pc[a] = "r_prev"
  /\ IF snapCur[a] /= None /\ snapCur[a] /= snapPrev[a]
       THEN /\ Go(a, "idle") /\ UNCHANGED <<cur, overwrote, restored>>
       ELSE /\ overwrote' = (overwrote \/ (cur /= None /\ cur /= snapPrev[a]))
            /\ cur' = snapPrev[a] /\ restored' = TRUE /\ Go(a, "idle")
  /\ Release
  /\ UNCHANGED <<prev, snapCur, snapPrev, lost>>

Next == \E a \in Actors :
          \/ \E e \in Edits : Set(a, e)
          \/ ClearCheck(a) \/ ClearLock(a) \/ ClearRead(a) \/ ClearExists(a) \/ ClearKeep(a) \/ ClearRemove(a)
          \/ RestoreCheck(a) \/ RestoreLock(a) \/ RestoreRead(a) \/ RestorePrev(a) \/ RestoreWrite(a)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
\* R1（S4a，photo_library.py:391-395）取回上一份時，絕不蓋掉一份不同的編輯
NoRestoreOverDifferent == ~overwrote
\* R2（S4，edit_store.py:139）被清掉的編輯，一定先留成上一份
NoLostEdit == ~lost
\* G1 一張照片可以設定編輯、清除、再取回（寫成「永遠取不回」，期待被違反）
NeverRestored == ~restored
=============================================================================
