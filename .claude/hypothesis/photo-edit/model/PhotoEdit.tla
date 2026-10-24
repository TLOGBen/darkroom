---------------------------- MODULE PhotoEdit ----------------------------
(* darkroom：一張照片的編輯、清除、取回上一份。                                   *)
(* 來源：darkroom_app/services/photo_library.py、adapters/persist/edit_store.py   *)
(* 每個動作的每一步都對到程式的一行（註解 file:line）；程式裡沒有鎖包住讀、比對、寫， *)
(* 所以每一步都是一個獨立的步驟。HTTP 請求跑在 worker thread（server.py:130），       *)
(* MCP 是另一個行程（mcp_server/__init__.py:1），兩者共用同一個資料夾。              *)
EXTENDS Naturals

CONSTANTS Locked,     \* FALSE = 現行程式；TRUE = 整段操作包在一個鎖裡（修法）
          NoRestore   \* TRUE = 拿掉「取回上一份」（看過它成功：目標應走不到）

Actors == {"app", "agent"}          \* App 的請求、AI 代理經 MCP 的請求
Edits  == {"A", "B"}                 \* 兩份不同的編輯
None   == "none"

VARIABLES cur,        \* 照片目前的編輯檔 edits/<fp>.json（edit_store.py:35-37）
          prev,       \* 留著的上一份 edits/<fp>.prev.json（edit_store.py:39-41）
          pc,         \* 每個請求做到哪一步
          snapCur,    \* 請求讀到的目前編輯
          snapPrev,   \* 請求讀到的上一份
          overwrote,  \* 曾經用取回蓋掉一份不同的編輯（R1 的反面）
          lost,       \* 曾經有一份編輯被清掉、卻沒留成上一份（R2 的反面）
          restored    \* 曾經成功取回上一份（目標 G1）

vars == <<cur, prev, pc, snapCur, snapPrev, overwrote, lost, restored>>

Init ==
  /\ cur = None /\ prev = None
  /\ pc = [a \in Actors |-> "idle"]
  /\ snapCur = [a \in Actors |-> None] /\ snapPrev = [a \in Actors |-> None]
  /\ overwrote = FALSE /\ lost = FALSE /\ restored = FALSE

Idle(a) == pc[a] = "idle"
Go(a, s) == pc' = [pc EXCEPT ![a] = s]

\* 設定編輯：整檔原子替換（photo_library.py:351 → edit_store.py:94 → locks.replace_atomic）
Set(a, e) ==
  /\ Idle(a)
  /\ cur' = e
  /\ UNCHANGED <<prev, pc, snapCur, snapPrev, overwrote, lost, restored>>

\* ---- 清除編輯（現行程式：四步）----
ClearRead(a) ==                     \* photo_library.py:358  existing = self.edits.read(...)
  /\ ~Locked /\ Idle(a)
  /\ snapCur' = [snapCur EXCEPT ![a] = cur] /\ Go(a, "c_read")
  /\ UNCHANGED <<cur, prev, snapPrev, overwrote, lost, restored>>
ClearExists(a) ==                   \* edit_store.py:99  if os.path.exists(p)
  /\ pc[a] = "c_read"
  /\ IF cur = None THEN Go(a, "idle") ELSE Go(a, "c_exists")
  /\ UNCHANGED <<cur, prev, snapCur, snapPrev, overwrote, lost, restored>>
ClearKeep(a) ==                     \* edit_store.py:101-103  write_json(prev_path, keep)
  /\ pc[a] = "c_exists"
  /\ prev' = IF snapCur[a] /= None THEN snapCur[a] ELSE prev
  /\ Go(a, "c_kept")
  /\ UNCHANGED <<cur, snapCur, snapPrev, overwrote, lost, restored>>
ClearRemove(a) ==                   \* edit_store.py:105  self.folder.remove(p)
  /\ pc[a] = "c_kept"
  /\ lost' = (lost \/ (cur /= None /\ cur /= snapCur[a]))
  /\ cur' = None /\ Go(a, "idle")
  /\ UNCHANGED <<prev, snapCur, snapPrev, overwrote, restored>>

\* ---- 取回上一份（現行程式：三步）----
RestoreRead(a) ==                   \* photo_library.py:366  current = self.edits.read(...)
  /\ ~Locked /\ ~NoRestore /\ Idle(a)
  /\ snapCur' = [snapCur EXCEPT ![a] = cur] /\ Go(a, "r_read")
  /\ UNCHANGED <<cur, prev, snapPrev, overwrote, lost, restored>>
RestorePrev(a) ==                   \* photo_library.py:367-369  prev = read_previous；沒有就 not_found
  /\ pc[a] = "r_read"
  /\ snapPrev' = [snapPrev EXCEPT ![a] = prev]
  /\ IF prev = None THEN Go(a, "idle") ELSE Go(a, "r_prev")
  /\ UNCHANGED <<cur, prev, snapCur, overwrote, lost, restored>>
RestoreWrite(a) ==                  \* photo_library.py:373-376  比對讀到的目前編輯，不同就 conflict，否則寫入
  /\ pc[a] = "r_prev"
  /\ IF snapCur[a] /= None /\ snapCur[a] /= snapPrev[a]
       THEN /\ Go(a, "idle") /\ UNCHANGED <<cur, overwrote, restored>>
       ELSE /\ overwrote' = (overwrote \/ (cur /= None /\ cur /= snapPrev[a]))
            /\ cur' = snapPrev[a] /\ restored' = TRUE /\ Go(a, "idle")
  /\ UNCHANGED <<prev, snapCur, snapPrev, lost>>

\* ---- 修法：整段操作在一個鎖裡，等於一步 ----
ClearLocked(a) ==
  /\ Locked /\ Idle(a) /\ cur /= None
  /\ prev' = cur /\ cur' = None
  /\ UNCHANGED <<pc, snapCur, snapPrev, overwrote, lost, restored>>
RestoreLocked(a) ==
  /\ Locked /\ ~NoRestore /\ Idle(a) /\ prev /= None /\ (cur = None \/ cur = prev)
  /\ cur' = prev /\ restored' = TRUE
  /\ UNCHANGED <<prev, pc, snapCur, snapPrev, overwrote, lost>>

Next == \E a \in Actors :
          \/ \E e \in Edits : Set(a, e)
          \/ ClearRead(a) \/ ClearExists(a) \/ ClearKeep(a) \/ ClearRemove(a)
          \/ RestoreRead(a) \/ RestorePrev(a) \/ RestoreWrite(a)
          \/ ClearLocked(a) \/ RestoreLocked(a)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
\* R1（S4a，photo_library.py:371-372）取回上一份時，絕不蓋掉一份不同的編輯
NoRestoreOverDifferent == ~overwrote
\* R2（S4，edit_store.py:97）被清掉的編輯，一定先留成上一份
NoLostEdit == ~lost
\* G1 一張照片可以設定編輯、清除、再取回（寫成「永遠取不回」，期待被違反）
NeverRestored == ~restored
=============================================================================
