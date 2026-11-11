# Requires bs_forwarded_proto/bs_forwarded_host maps from the repository default.conf.
proxy_pass http://gateway:8080;
proxy_http_version 1.1;
proxy_set_header Host $http_host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $bs_forwarded_proto;
proxy_set_header X-Forwarded-Host $bs_forwarded_host;
proxy_set_header Connection "";
proxy_buffering off;
proxy_read_timeout 60s;
client_max_body_size 16k;
