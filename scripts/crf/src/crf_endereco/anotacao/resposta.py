"""Respostas da LLM e sua validacao."""
import json
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    idx: str
    nome: str
    argumentos: Any

@dataclass
class Segmento:
    valor: str
    tipo: str

@dataclass
class RespostaFinal:
    segmentos: list[Segmento]
    comentario: str | None

@dataclass
class RespostaModelo:
    resposta: str | None
    raciociono: str
    tool_calls: list[ToolCall]
    message_original: Any

    def obter_resposta_final(self) -> ToolCall | None:
        return next((c for c in self.tool_calls if c.nome == "responder"), None)

def estruturar_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    resultado: list[ToolCall] = []
    for call in message.get("tool_calls", []):
        funcao = call.get("function", {})
        try:
            argumentos = json.loads(funcao.get("arguments"))
        except (json.JSONDecodeError, TypeError):
            continue

        resultado.append(
            ToolCall(
                idx=call.get("id", ""),
                nome=funcao.get("name", ""),
                argumentos=argumentos,
            )
        )
    return resultado

def estruturar_resposta_modelo(resposta_bruta: dict[str, Any]) -> RespostaModelo:
    message = resposta_bruta.get("choices", [{}])[0].get("message", {})
    return RespostaModelo(
        resposta=message.get("content"),
        raciociono=message.get("reasoning", ""),
        tool_calls=estruturar_tool_calls(message),
        message_original=message,
    )

def processar_resultado_final(chamada: ToolCall) -> RespostaFinal:
    """Converte a chamada `responder` na resposta final estruturada."""
    segmentos = [
        Segmento(valor=str(seg.get("valor", "")), tipo=str(seg.get("tipo", "")))
        for seg in chamada.argumentos.get("segmentos", [])
    ]
    return RespostaFinal(
        segmentos=segmentos, comentario=chamada.argumentos.get("comentario")
    )

def validar_resposta_final(
    endereco: str, resposta: RespostaFinal
) -> tuple[str, str | None]:
    """Confere que cada segmento é um trecho verbatim e na ordem do endereço.

    Retorna a visualização anotada e, se houver, a descrição dos problemas.
    """
    ultima_pos = 0
    problemas: list[str] = []
    visualizacao: list[str] = []

    for i, seg in enumerate(resposta.segmentos):
        posicao = endereco.find(seg.valor, ultima_pos)

        if posicao == -1:
            problemas.append(
                f"Could not locate segment #{i + 1}: {seg.valor} ({seg.tipo}) "
            )
            continue

        if posicao != ultima_pos:
            visualizacao.append(endereco[ultima_pos:posicao])

        fim = posicao + len(seg.valor)
        visualizacao.append(f"{endereco[posicao:fim]} [{seg.tipo}]")
        ultima_pos = fim

    if ultima_pos != len(endereco):
        visualizacao.append(endereco[ultima_pos:])

    problemas_str = "\n".join(problemas) if problemas else None
    return "\n".join(visualizacao), problemas_str

class ErroSegmentacao(RuntimeError):
    """Não foi possível obter uma segmentação válida."""
