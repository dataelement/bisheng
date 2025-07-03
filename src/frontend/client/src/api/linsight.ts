import request from "./request";

// 灵思
export function getTools(name: string): Promise<any> {
  return request.get('/api/v1/download?object_name=' + name);
}