interface ComposerMenuTextProps {
  name: string;
  description?: string;
}

/** Shared typography and baseline alignment for composer tools and skills. */
export function ComposerMenuText({ name, description }: ComposerMenuTextProps) {
  return (
    <div className="dsh-command-resource-text min-w-0 flex-1">
      <p className="dsh-command-name text-text-1">{name}</p>
      {description && <p className="dsh-command-description">{description}</p>}
    </div>
  );
}
