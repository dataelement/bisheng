import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSelectableSkills } from '~/api/linsight';
import type { TaskModeSkill } from '~/store/linsight';
import type { SelectedAgentTool } from '~/store/modeltype';
import type { AvailableToolGroup } from '~/components/Chat/Input/AgentToolSelector';
import type { WorkspaceScene } from './scenes';

type Selection = { skills: TaskModeSkill[]; tools: SelectedAgentTool[]; taskMode: boolean; searchType: string };
interface AdvisorEntryProps extends Selection {
  scene: WorkspaceScene;
  config?: { tools?: AvailableToolGroup[] };
  canUseTaskMode: boolean;
  setSkills: (skills: TaskModeSkill[]) => void;
  setTools: (tools: SelectedAgentTool[]) => void;
  setTaskMode: (enabled: boolean) => void;
  setSearchType: (type: string) => void;
}

export function useAdvisorEntry(props: AdvisorEntryProps) {
  const { scene, config, skills, tools, taskMode, searchType, canUseTaskMode, setSkills, setTools, setTaskMode, setSearchType } = props;
  const selected = !!scene && scene !== 'select';
  const catalog = useQuery({ queryKey: ['linsightSelectableSkills'], queryFn: getSelectableSkills, enabled: selected, retry: false, staleTime: 0, refetchOnWindowFocus: true });
  const skillName = scene === 'orders' ? 'order-tracking' : scene === 'customs' ? 'customs-history' : scene === 'transport' ? 'transport-native-api' : 'procurement-history';
  const skill = catalog.data?.find(item => item.name === skillName);
  const groups = config?.tools || [];
  const groupFor = (key: string, byName = false) => groups.find(group => group.children?.some(child => (byName ? child.name : child.tool_key) === key && child.enabled !== false));
  const api = groupFor('query_procurement_history', true) || groupFor('tool_type_21_df150bfcffc4d3a398f68301818e9165');
  const code = groupFor('bisheng_code_interpreter');
  const transport = groupFor('transport_execute', true);
  const available = selected && !!skill && canUseTaskMode && (scene === 'transport' ? !!transport : !!code && (scene !== 'procurement' || !!api));
  const wantedTools: SelectedAgentTool[] = (available ? scene === 'transport' ? [transport!] : scene === 'procurement' ? [api!, code!] : [code!] : []).map(group => ({
    id: group.id, name: group.name, description: group.description,
    children: (group.children || []).filter(child => child.enabled !== false).map(child => ({ id: child.id, tool_key: child.tool_key, name: child.name, desc: child.desc || child.description })),
  }));
  const toolsKey = JSON.stringify(wantedTools);
  const match = available && skills.length === 1 && skills[0].name === skill?.name && JSON.stringify(tools) === toolsKey && taskMode && searchType === '';
  const snapshot = useRef<Selection | null>(null);
  const latest = useRef(props);
  latest.current = props;
  useEffect(() => {
    if (!selected || !available) return;
    if (!snapshot.current) snapshot.current = { skills, tools, taskMode, searchType };
    if (skills.length !== 1 || skills[0].name !== skill?.name) setSkills([skill!]);
    if (JSON.stringify(tools) !== toolsKey) setTools(JSON.parse(toolsKey) as SelectedAgentTool[]);
    if (!taskMode) setTaskMode(true);
    if (searchType) setSearchType('');
  }, [selected, available, skill, skills, tools, toolsKey, taskMode, searchType, setSkills, setTools, setTaskMode, setSearchType]);
  useEffect(() => () => {
    const prior = snapshot.current;
    if (!prior) return;
    snapshot.current = null;
    latest.current.setSkills(prior.skills); latest.current.setTools(prior.tools);
    latest.current.setTaskMode(prior.taskMode); latest.current.setSearchType(prior.searchType);
  }, [selected]);
  const [timedOut, setTimedOut] = useState(false);
  useEffect(() => {
    setTimedOut(false);
    if (!selected || match) return;
    const timer = window.setTimeout(() => setTimedOut(true), 12000);
    return () => window.clearTimeout(timer);
  }, [selected, scene, match, catalog.isFetching]);
  return {
    ready: !selected || match,
    error: selected && (catalog.isError || timedOut || (!!config && !!catalog.data && !available)),
    retry: () => { setTimedOut(false); void catalog.refetch(); },
    transportToolKey: transport?.children?.find(child => child.name === 'transport_execute' && child.enabled !== false)?.tool_key,
  };
}
