 export interface User {
    user_name: string;
    email: string | null;
    phone_number: string | null;
    remark: string | null;
    delete: number;
    create_time: string;
    update_time: string;
    user_id: number;
    role: string;
}