export interface MoveSpace {
  id: string;
  name: string;
}

export interface MoveFolder {
  id: string;
  name: string;
}

export interface MoveDestinationItem extends MoveFolder {
  type: 'folder' | 'file';
}

export interface MoveSpaceGroups {
  department: MoveSpace[];
  created: MoveSpace[];
  joined: MoveSpace[];
  /** Additional management-visible destinations, still authorized by server precheck. */
  available?: MoveSpace[];
}

export interface MoveCatalogHooks {
  /** Called as soon as a page can be shown. The returned promise is still the complete catalog. */
  onPartial?: (groups: MoveSpaceGroups) => void;
}

/** Hosts own authentication, management scope, permission filtering and pagination. */
export interface MoveDestinationServices {
  listSpaces: (signal: AbortSignal, hooks?: MoveCatalogHooks) => Promise<MoveSpaceGroups>;
  /** Narrow the catalog on the server. Hosts without this keep filtering the loaded list. */
  searchSpaces?: (keyword: string, signal: AbortSignal, hooks?: MoveCatalogHooks) => Promise<MoveSpaceGroups>;
  listFolders: (spaceId: string, parentId: string | null, signal: AbortSignal) => Promise<MoveFolder[]>;
  listChildren: (spaceId: string, parentId: string | null, signal: AbortSignal) => Promise<MoveDestinationItem[]>;
}

export interface MoveTarget {
  spaceId: string;
  folderId: string | null;
  folderName?: string;
}
