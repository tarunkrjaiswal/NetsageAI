create or replace view public.responsible_ai_log as
select
    d.id as diagnosis_id,
    d.case_ref,
    d.category,
    d.root_cause as ai_diagnosis,
    d.confidence as ai_confidence,
    r.decision as human_decision,
    r.human_root_cause as human_diagnosis,
    r.reason,
    r.reviewed_at
from public.diagnoses d
left join public.reviews r on r.diagnosis_id = d.id
order by r.reviewed_at desc;
