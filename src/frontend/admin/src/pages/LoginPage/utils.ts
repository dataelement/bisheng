import { getPublicKeyApi } from "@/controllers/API/user";
import { getKeyApi } from "@/controllers/API/pro";
import { JSEncrypt } from 'jsencrypt';

export const handleEncrypt = async (pwd: string): Promise<string> => {
    const { public_key } = await getPublicKeyApi();
    const encrypt = new JSEncrypt();
    encrypt.setPublicKey(public_key);
    return encrypt.encrypt(pwd) as string;
};

export const handleLdapEncrypt = async (pwd: string): Promise<string> => {
    const public_key:any = await getKeyApi();
    const encrypt = new JSEncrypt();
    encrypt.setPublicKey(public_key);
    return encrypt.encrypt(pwd) as string;
};

export const PWD_RULE = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{8,}$/