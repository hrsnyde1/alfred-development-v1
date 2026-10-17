// Extract only native, SDK-owned fields. Never use content.target or a model value.
export function extractNativeEvent(space, message) {
  const content = message?.content;
  return {
    spaceId: space?.id,
    spaceType: space?.type,
    messageId: message?.id,
    senderId: message?.sender?.id,
    senderService: message?.sender?.service,
    direction: message?.direction,
    replyTargetGuid: message?.nativeReplyTargetGuid,
    threadOriginatorGuid: message?.nativeThreadOriginatorGuid,
    isForward: message?.nativeIsForward,
    text: content?.type === "text" ? content.text : undefined,
  };
}
