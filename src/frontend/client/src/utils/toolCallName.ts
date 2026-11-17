/** Keep legacy image tool identifiers readable in current and saved execution rows. */
export function toolCallDisplayName(name: string): string {
  return ['dalle_image_generator', 'image_generation'].includes(name.toLowerCase())
    ? 'image_generator'
    : name;
}
