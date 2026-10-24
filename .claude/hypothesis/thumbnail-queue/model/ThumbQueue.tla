---------------------------- MODULE ThumbQueue ----------------------------
(* darkroom：縮圖格的背景縮圖佇列。                                                *)
(* 來源：darkroom_app/services/photo_library.py（_ThumbQueue、folder_thumbnails、   *)
(* thumbnail、_generate）、adapters/persist/thumb_store.py（lookup、remember）。      *)
(* 每個動作是程式裡不可再分的一步（註解 file:line）：佇列的操作都握著 self.cv，       *)
(* 一步做完；列資料夾時「查有沒有縮圖」與「送進佇列」是兩個迴圈，中間不握任何鎖。     *)
(* 情境照 tests/test_photo_library.py:1113 的測試：列一次資料夾 → 直接要最後一張 →    *)
(* 再列一次同一個資料夾；另有「照片檔被改了」的事件（MaxV > 0 時）。                  *)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS N,          \* 資料夾裡的照片數（依檔名順序 1..N）
          Workers,    \* 縮圖工作執行緒（THUMB_WORKERS 個）
          MaxV,       \* 每張照片最多被改幾次（0 = 不改）
          CheckInflight,   \* TRUE = 現行程式；FALSE = 送進佇列不看「處理中」（R1 的壞掉版本）
          RecheckInSubmit, \* TRUE = 修法參考：送進佇列時（握著佇列鎖）不在處理中就再查一次索引
          NoMake           \* TRUE = 拿掉「工作做完記進索引」這一步（G1 看過它成功用）

Photos == 1..N
NoV == 99             \* 索引裡沒有這張

VARIABLES ver,        \* 照片檔目前的版本（大小＋修改時間，thumb_store.py:109 比的就是它）
          idx,        \* 記憶體索引記住的版本（thumb_store.py:113-118 remember）
          queue,      \* 佇列裡還沒開始的工作 <<[p, prio, gen, seq]>>（photo_library.py:118-158）
          seqc,       \* 送入順序（self.seq）
          run,        \* 每個工作執行緒：idle／work（正在做）／fin（做完、還沒離開處理中）
          gen,        \* 這個資料夾的世代號（self.generation[folder]）
          made,       \* 這個版本的照片被做了幾次縮圖工作
          redo,       \* 已有一次工作的版本又被做的次數（R2、R3 的反面）
          dup,        \* 曾經同一張照片同時有兩個工作（R1 的反面）
          m           \* 主執行緒（測試／App 的請求）做到哪一步

vars == <<ver, idx, queue, seqc, run, gen, made, redo, dup, m>>

Init ==
  /\ ver = [p \in Photos |-> 0] /\ idx = [p \in Photos |-> NoV]
  /\ queue = <<>> /\ seqc = 0 /\ gen = 0
  /\ run = [w \in Workers |-> [st |-> "idle", p |-> 0, v |-> 0]]
  /\ made = [p \in Photos |-> 0] /\ redo = 0 /\ dup = FALSE
  /\ m = [step |-> "L1", ph |-> "lookup", i |-> 1, todo |-> <<>>]

Cached(p) == idx[p] = ver[p]                       \* lookup 命中＋縮圖檔存在（:519-523）
Queued(p) == \E k \in 1..Len(queue) : queue[k].p = p
InFlight(p) == Queued(p) \/ \E w \in Workers : run[w].st \in {"work", "fin"} /\ run[w].p = p
Pos(p) == CHOOSE k \in 1..Len(queue) : queue[k].p = p
Remove(s, k) == SubSeq(s, 1, k - 1) \o SubSeq(s, k + 1, Len(s))

\* _ThumbQueue.submit（photo_library.py:136-158），握著 self.cv，一步
SubmitQ(p, prio) ==
  IF CheckInflight /\ InFlight(p)
    THEN /\ queue' = IF Queued(p)                  \* :145-149 還沒開始：變回目前世代，直接請求插隊
                       THEN [queue EXCEPT ![Pos(p)].gen = gen,
                                          ![Pos(p)].prio = IF prio < queue[Pos(p)].prio THEN prio
                                                           ELSE queue[Pos(p)].prio]
                       ELSE queue                  \* :150 正在做：等同一個結果
         /\ UNCHANGED <<seqc, dup>>
    ELSE IF RecheckInSubmit /\ Cached(p)
      THEN UNCHANGED <<queue, seqc, dup>>          \* 修法參考：已經做好就不排
      ELSE /\ queue' = Append(queue, [p |-> p, prio |-> prio, gen |-> gen, seq |-> seqc + 1])   \* :151-157
           /\ seqc' = seqc + 1
           /\ dup' = (dup \/ InFlight(p))

NextStep(s) == CASE s = "L1" -> "D" [] s = "D" -> "L2" [] OTHER -> "done"
Begin(s) == IF s = "D" THEN [step |-> "D", ph |-> "dlook", i |-> 1, todo |-> <<>>]
            ELSE IF s = "done" THEN [step |-> "done", ph |-> "none", i |-> 1, todo |-> <<>>]
            ELSE [step |-> s, ph |-> "lookup", i |-> 1, todo |-> <<>>]

\* ---- 列資料夾（folder_thumbnails，photo_library.py:516-530）----
ListLookup ==                                       \* :516-527 一張一張查，沒縮圖的記進 todo
  /\ m.step \in {"L1", "L2"} /\ m.ph = "lookup"
  /\ m' = [m EXCEPT !.todo = IF Cached(m.i) THEN m.todo ELSE Append(m.todo, m.i),
                    !.i = m.i + 1, !.ph = IF m.i = N THEN "gen" ELSE "lookup"]
  /\ UNCHANGED <<ver, idx, queue, seqc, run, gen, made, redo, dup>>
ListGen ==                                          \* :528 new_generation
  /\ m.step \in {"L1", "L2"} /\ m.ph = "gen"
  /\ gen' = gen + 1
  /\ m' = IF Len(m.todo) = 0 THEN Begin(NextStep(m.step)) ELSE [m EXCEPT !.ph = "submit", !.i = 1]
  /\ UNCHANGED <<ver, idx, queue, seqc, run, made, redo, dup>>
ListSubmit ==                                       \* :529-530 todo 一張一張送進佇列
  /\ m.step \in {"L1", "L2"} /\ m.ph = "submit"
  /\ SubmitQ(m.todo[m.i], 1)
  /\ m' = IF m.i = Len(m.todo) THEN Begin(NextStep(m.step)) ELSE [m EXCEPT !.i = m.i + 1]
  /\ UNCHANGED <<ver, idx, run, gen, made, redo>>

\* ---- 直接要最後一張（thumbnail，photo_library.py:540-550）----
DirectLook ==                                       \* :543-548 索引命中就直接讀，不排隊
  /\ m.step = "D" /\ m.ph = "dlook"
  /\ m' = IF Cached(N) THEN Begin("L2") ELSE [m EXCEPT !.ph = "dsubmit"]
  /\ UNCHANGED <<ver, idx, queue, seqc, run, gen, made, redo, dup>>
DirectSubmit ==                                     \* :550 submit(path, folder, 0)
  /\ m.step = "D" /\ m.ph = "dsubmit"
  /\ SubmitQ(N, 0)
  /\ m' = [m EXCEPT !.ph = "dwait"]
  /\ UNCHANGED <<ver, idx, run, gen, made, redo>>
DirectWait ==                                       \* :550 .wait()：那個工作離開處理中
  /\ m.step = "D" /\ m.ph = "dwait" /\ ~InFlight(N)
  /\ m' = Begin("L2")
  /\ UNCHANGED <<ver, idx, queue, seqc, run, gen, made, redo, dup>>

\* ---- 縮圖工作執行緒（_ThumbQueue._run，photo_library.py:182-211）----
MinK == CHOOSE k \in 1..Len(queue) : \A j \in 1..Len(queue) :
          <<queue[k].prio, queue[k].seq>> = <<queue[j].prio, queue[j].seq>> \/
          queue[k].prio < queue[j].prio \/ (queue[k].prio = queue[j].prio /\ queue[k].seq < queue[j].seq)
Take(w) ==                                          \* :186-195 取最急的；過期的背景工作直接丟掉
  /\ run[w].st = "idle" /\ Len(queue) > 0
  /\ LET k == MinK  e == queue[k] IN
     /\ queue' = Remove(queue, k)
     /\ IF e.prio = 1 /\ e.gen # gen
          THEN UNCHANGED <<run, made, redo>>        \* :192-195 stale：不做，離開處理中
          ELSE /\ run' = [run EXCEPT ![w] = [st |-> "work", p |-> e.p, v |-> ver[e.p]]]   \* :198 → _generate :478-480 讀檔
               /\ made' = [made EXCEPT ![e.p] = @ + 1]
               /\ redo' = redo + (IF made[e.p] >= 1 THEN 1 ELSE 0)
  /\ UNCHANGED <<ver, idx, seqc, gen, dup, m>>
WorkDone(w) ==                                      \* _generate :493 remember（讀檔時的版本）
  /\ ~NoMake /\ run[w].st = "work"
  /\ idx' = [idx EXCEPT ![run[w].p] = run[w].v]
  /\ run' = [run EXCEPT ![w].st = "fin"]
  /\ UNCHANGED <<ver, queue, seqc, gen, made, redo, dup, m>>
Release(w) ==                                       \* :203-206 離開處理中、交出結果
  /\ run[w].st = "fin"
  /\ run' = [run EXCEPT ![w] = [st |-> "idle", p |-> 0, v |-> 0]]
  /\ UNCHANGED <<ver, idx, queue, seqc, gen, made, redo, dup, m>>

\* ---- 照片檔被改了（大小或修改時間變了）----
Update(p) ==
  /\ ver[p] < MaxV
  /\ ver' = [ver EXCEPT ![p] = @ + 1] /\ made' = [made EXCEPT ![p] = 0]
  /\ UNCHANGED <<idx, queue, seqc, run, gen, redo, dup, m>>

Next == \/ ListLookup \/ ListGen \/ ListSubmit \/ DirectLook \/ DirectSubmit \/ DirectWait
        \/ \E w \in Workers : Take(w) \/ WorkDone(w) \/ Release(w)
        \/ \E p \in Photos : Update(p)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
\* R1（PLP8「同一張照片同時只有一個工作」；photo_library.py:143-150）
OneJobPerPhoto == ~dup
\* R2（PLP8「已在快取的照片在排入前就以索引過濾掉」；使用者：更新後才會重縮）
NoRedoUnlessUpdated == redo = 0
\* R3（測試的假設，tests/test_photo_library.py:1141：重做不超過工作執行緒數）
RedoAtMostWorkers == redo <= Cardinality(Workers)
\* G1 列資料夾之後每張照片都有縮圖（寫成「永遠做不完」，期待被違反）
NeverAllDone == ~(m.step = "done" /\ \A p \in Photos : Cached(p))
=============================================================================
