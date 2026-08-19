// Inserts a raw __wildcard__ token into the native txt2img/img2img prompt
// textarea. Pure client-side: sd-dynamic-prompts resolves the token later, at
// generation time, exactly as it already does for hand-typed wildcards.
function wcInsertWildcardInto(elemId, wildcardName) {
    if (!wildcardName) {
        return [];
    }
    const container = gradioApp().getElementById(elemId);
    if (!container) {
        return [];
    }
    const textarea = container.querySelector("textarea");
    if (!textarea) {
        return [];
    }

    const token = `__${wildcardName}__`;
    const current = textarea.value;
    const needsSeparator = current.length > 0 && !/[,\n]\s*$/.test(current);
    textarea.value = current + (needsSeparator ? ", " : "") + token;

    updateInput(textarea);
    return [];
}

function wcInsertWildcardT2I(wildcardName) {
    return wcInsertWildcardInto("txt2img_prompt", wildcardName);
}

function wcInsertWildcardI2I(wildcardName) {
    return wcInsertWildcardInto("img2img_prompt", wildcardName);
}
