---- MODULE EvidenceMediatedGovernance_Broken_TTrace_1785791340 ----
EXTENDS Sequences, TLCExt, Toolbox, Naturals, TLC, EvidenceMediatedGovernance_Broken_TEConstants, EvidenceMediatedGovernance_Broken

_expression ==
    LET EvidenceMediatedGovernance_Broken_TEExpression == INSTANCE EvidenceMediatedGovernance_Broken_TEExpression
    IN EvidenceMediatedGovernance_Broken_TEExpression!expression
----

_trace ==
    LET EvidenceMediatedGovernance_Broken_TETrace == INSTANCE EvidenceMediatedGovernance_Broken_TETrace
    IN EvidenceMediatedGovernance_Broken_TETrace!trace
----

_inv ==
    ~(
        TLCGet("level") = Len(_TETrace)
        /\
        authorized = (TRUE)
        /\
        reviewed = ((r1 :> FALSE @@ r2 :> FALSE @@ r3 :> FALSE @@ r4 :> FALSE @@ r5 :> FALSE))
        /\
        pendingRisk = ({r1})
    )
----

_init ==
    /\ reviewed = _TETrace[1].reviewed
    /\ authorized = _TETrace[1].authorized
    /\ pendingRisk = _TETrace[1].pendingRisk
----

_next ==
    /\ \E i,j \in DOMAIN _TETrace:
        /\ \/ /\ j = i + 1
              /\ i = TLCGet("level")
        /\ reviewed  = _TETrace[i].reviewed
        /\ reviewed' = _TETrace[j].reviewed
        /\ authorized  = _TETrace[i].authorized
        /\ authorized' = _TETrace[j].authorized
        /\ pendingRisk  = _TETrace[i].pendingRisk
        /\ pendingRisk' = _TETrace[j].pendingRisk

\* Uncomment the ASSUME below to write the states of the error trace
\* to the given file in Json format. Note that you can pass any tuple
\* to `JsonSerialize`. For example, a sub-sequence of _TETrace.
    \* ASSUME
    \*     LET J == INSTANCE Json
    \*         IN J!JsonSerialize("EvidenceMediatedGovernance_Broken_TTrace_1785791340.json", _TETrace)

=============================================================================

 Note that you can extract this module `EvidenceMediatedGovernance_Broken_TEExpression`
  to a dedicated file to reuse `expression` (the module in the 
  dedicated `EvidenceMediatedGovernance_Broken_TEExpression.tla` file takes precedence 
  over the module `EvidenceMediatedGovernance_Broken_TEExpression` below).

---- MODULE EvidenceMediatedGovernance_Broken_TEExpression ----
EXTENDS Sequences, TLCExt, Toolbox, Naturals, TLC, EvidenceMediatedGovernance_Broken_TEConstants, EvidenceMediatedGovernance_Broken

expression == 
    [
        \* To hide variables of the `EvidenceMediatedGovernance_Broken` spec from the error trace,
        \* remove the variables below.  The trace will be written in the order
        \* of the fields of this record.
        reviewed |-> reviewed
        ,authorized |-> authorized
        ,pendingRisk |-> pendingRisk
        
        \* Put additional constant-, state-, and action-level expressions here:
        \* ,_stateNumber |-> _TEPosition
        \* ,_reviewedUnchanged |-> reviewed = reviewed'
        
        \* Format the `reviewed` variable as Json value.
        \* ,_reviewedJson |->
        \*     LET J == INSTANCE Json
        \*     IN J!ToJson(reviewed)
        
        \* Lastly, you may build expressions over arbitrary sets of states by
        \* leveraging the _TETrace operator.  For example, this is how to
        \* count the number of times a spec variable changed up to the current
        \* state in the trace.
        \* ,_reviewedModCount |->
        \*     LET F[s \in DOMAIN _TETrace] ==
        \*         IF s = 1 THEN 0
        \*         ELSE IF _TETrace[s].reviewed # _TETrace[s-1].reviewed
        \*             THEN 1 + F[s-1] ELSE F[s-1]
        \*     IN F[_TEPosition - 1]
    ]

=============================================================================



Parsing and semantic processing can take forever if the trace below is long.
 In this case, it is advised to uncomment the module below to deserialize the
 trace from a generated binary file.

\*
\*---- MODULE EvidenceMediatedGovernance_Broken_TETrace ----
\*EXTENDS IOUtils, TLC, EvidenceMediatedGovernance_Broken_TEConstants, EvidenceMediatedGovernance_Broken
\*
\*trace == IODeserialize("EvidenceMediatedGovernance_Broken_TTrace_1785791340.bin", TRUE)
\*
\*=============================================================================
\*

---- MODULE EvidenceMediatedGovernance_Broken_TETrace ----
EXTENDS TLC, EvidenceMediatedGovernance_Broken_TEConstants, EvidenceMediatedGovernance_Broken

trace == 
    <<
    ([authorized |-> FALSE,reviewed |-> (r1 :> FALSE @@ r2 :> FALSE @@ r3 :> FALSE @@ r4 :> FALSE @@ r5 :> FALSE),pendingRisk |-> {}]),
    ([authorized |-> FALSE,reviewed |-> (r1 :> FALSE @@ r2 :> FALSE @@ r3 :> FALSE @@ r4 :> FALSE @@ r5 :> FALSE),pendingRisk |-> {r1}]),
    ([authorized |-> TRUE,reviewed |-> (r1 :> FALSE @@ r2 :> FALSE @@ r3 :> FALSE @@ r4 :> FALSE @@ r5 :> FALSE),pendingRisk |-> {r1}])
    >>
----


=============================================================================

---- MODULE EvidenceMediatedGovernance_Broken_TEConstants ----
EXTENDS EvidenceMediatedGovernance_Broken

CONSTANTS r1, r2, r3, r4, r5

=============================================================================

---- CONFIG EvidenceMediatedGovernance_Broken_TTrace_1785791340 ----
CONSTANTS
    RiskSignals = { r1 , r2 , r3 , r4 , r5 }
    MaxSteps = 5
    r3 = r3
    r5 = r5
    r2 = r2
    r4 = r4
    r1 = r1

INVARIANT
    _inv

CHECK_DEADLOCK
    \* CHECK_DEADLOCK off because of PROPERTY or INVARIANT above.
    FALSE

INIT
    _init

NEXT
    _next

CONSTANT
    _TETrace <- _trace

ALIAS
    _expression
=============================================================================
\* Generated on Mon Aug 03 23:09:01 CEST 2026