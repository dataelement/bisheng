import { useQuery } from '@tanstack/react-query';
import { readFileCapabilities } from '~/api/knowledgeProviderUploads';
import { useAuthContext } from '~/hooks';

export type TagScope =
  | { kind: 'unavailable' }
  | { kind: 'native'; key: string }
  | { kind: 'provider'; key: string; generation: number; tenant: string; editable: boolean };

export function useSpaceCapabilities(spaceId: string) {
  const { user } = useAuthContext();
  const identity = JSON.stringify([user?.id, user?.role, user?.tenant_id]);
  const capabilities = useQuery({
    queryKey: ['knowledge-file-capabilities', identity, spaceId],
    queryFn: ({ signal }) => readFileCapabilities(spaceId, signal), retry: false, cacheTime: 0,
    keepPreviousData: false, enabled: !!spaceId,
  });
  const proof = capabilities.isSuccess && !capabilities.isFetching ? capabilities.data : undefined;
  const key = JSON.stringify([spaceId, identity, proof?.tenant, proof?.generation, proof?.revision]);
  const tagScope: TagScope = proof?.native && /^[1-9]\d*$/.test(proof.tenant) ? { kind: 'native', key }
    : proof?.tagReadable && proof.generation && /^[1-9]\d*$/.test(proof.tenant)
      ? { kind: 'provider', tenant: proof.tenant, generation: proof.generation, editable: proof.tagEditable, key }
      : { kind: 'unavailable' };
  return { identity, capabilities, proof, tagScope };
}
