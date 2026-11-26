export type OAuth2ClientType = 'public' | 'confidential'

export interface OAuth2ClientItem {
    id: number
    client_id: string
    client_name: string
    description?: string | null
    client_type: OAuth2ClientType
    has_secret: boolean
    redirect_uris: string[]
    allow_loopback_port: boolean
    allowed_scopes: string[]
    grant_types: string[]
    require_pkce: boolean
    require_consent: boolean
    enabled: boolean
    is_builtin: boolean
    access_token_ttl: number
    refresh_token_ttl: number
    create_time?: string | null
    update_time?: string | null
}

export interface OAuth2ClientCreateInput {
    client_id?: string
    client_name: string
    description?: string | null
    client_type: OAuth2ClientType
    redirect_uris: string[]
    allow_loopback_port: boolean
    allowed_scopes: string[]
    grant_types: string[]
    require_pkce: boolean
    require_consent: boolean
    enabled: boolean
    access_token_ttl: number
    refresh_token_ttl: number
}

export interface OAuth2ClientUpdateInput {
    client_name?: string
    description?: string | null
    redirect_uris?: string[]
    allow_loopback_port?: boolean
    allowed_scopes?: string[]
    grant_types?: string[]
    require_pkce?: boolean
    require_consent?: boolean
    enabled?: boolean
    access_token_ttl?: number
    refresh_token_ttl?: number
}

export interface OAuth2ClientSecretResult {
    client: OAuth2ClientItem
    client_secret?: string | null
}

export interface OAuth2ConsentDetails {
    request_id: string
    client_id: string
    client_name: string
    client_description?: string | null
    scopes: string[]
    redirect_uri: string
    state?: string | null
    require_consent: boolean
    expires_in: number
}

export interface OAuth2ConsentDecisionResult {
    redirect_uri: string
}
