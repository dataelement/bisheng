import aiohttp


async def get_url_content(url: str) -> str:
    """ Get the returned of the interfacebodyContents """
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f'Failed to download content, HTTP status code: {response.status}')
            res = await response.read()
            return res.decode('utf-8')
