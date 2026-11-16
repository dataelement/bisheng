import { toolCallDisplayName } from './toolCallName';

test.each(['dalle_image_generator', 'image_generation', 'DALLE_IMAGE_GENERATOR'])(
  'image execution name %s displays as image_generator', (name) => {
    expect(toolCallDisplayName(name)).toBe('image_generator');
  },
);

test.each(['image_generator', 'web_search', 'Custom drawing tool', ''])(
  'preserves other execution names: %s', (name) => {
    expect(toolCallDisplayName(name)).toBe(name);
  },
);
