import { Navigate, useSearchParams } from 'react-router-dom';
export function SkillCenterPage() {
  const [params] = useSearchParams();
  const next = new URLSearchParams({ type: 'skill' });
  if (params.get('skill')) next.set('skill', params.get('skill')!);
  return <Navigate replace to={`/capabilities?${next}`} />;
}
