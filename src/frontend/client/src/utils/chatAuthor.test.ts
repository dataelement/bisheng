import { resolveChatAuthor } from './chatAuthor';

const viewer = { id: '7', username: 'Alex', avatar: '/alex.png' };

it('uses the latest viewer profile for their own authenticated conversation', () => {
  expect(resolveChatAuthor({ user_id: 7, user_name: 'Old Alex' }, viewer)).toEqual({
    name: 'Alex', avatar: '/alex.png',
  });
  expect(resolveChatAuthor({}, viewer)).toEqual({ name: 'Alex', avatar: '/alex.png' });
});

it('does not use the viewer avatar for another or unverified author with the same name', () => {
  expect(resolveChatAuthor({ user_id: 8, user_name: 'Alex' }, viewer)).toEqual({ name: 'Alex', avatar: undefined });
  expect(resolveChatAuthor({ user_name: 'Alex' }, viewer)).toEqual({ name: 'Alex', avatar: undefined });
  expect(resolveChatAuthor({ user_id: 8 }, viewer)).toEqual({ name: undefined, avatar: undefined });
});

it('uses only the author data made available for a shared conversation', () => {
  expect(resolveChatAuthor({ user_id: 7, user_name: 'Public name' })).toEqual({ name: 'Public name', avatar: undefined });
  const avatar = '/object/bisheng/avatar/8/picture.png?signature=a%2Bb';
  expect(resolveChatAuthor({ user_id: 8, user_name: 'Writer', user_avatar: avatar }, viewer)).toEqual({
    name: 'Writer', avatar,
  });
  expect(resolveChatAuthor({})).toEqual({ name: undefined, avatar: undefined });
});
