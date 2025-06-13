import { Box, Text } from '@radix-ui/themes';
import { MessageSquareMore } from "lucide-react";

const MsgVNodeCom = ({ message }) => {
    return <Box className="bg-[#fdb136] text-primary-foreground"
        style={{
            display: 'flex',
            border: "1px solid #d1d5da",
            borderRadius: '4px',
            padding: '4px 10px',
            opacity: '0.8'
        }}
    >
        <MessageSquareMore width={20} />
        <Text>{message}</Text>
    </Box>
}

export default MsgVNodeCom;