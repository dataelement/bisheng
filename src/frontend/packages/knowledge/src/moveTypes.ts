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

/** Hosts own authentication, management scope, permission filtering and pagination. */
export interface MoveDestinationServices {
  listSpaces: (signal: AbortSignal) => Promise<MoveSpaceGroups>;
  listFolders: (spaceId: string, parentId: string | null, signal: AbortSignal) => Promise<MoveFolder[]>;
  listChildren: (spaceId: string, parentId: string | null, signal: AbortSignal) => Promise<MoveDestinationItem[]>;
}

export interface MoveTarget {
  spaceId: string;
  folderId: string | null;
  folderName?: string;
}
