import argparse
import os
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from optimum.neuron import NeuronModelForCausalLM


def load_llm_optimum(model_id_or_path, batch_size, seq_length, num_cores, auto_cast_type):
    export = not os.path.isdir(model_id_or_path)

    # Load and convert the Hub model to Neuron format
    return NeuronModelForCausalLM.from_pretrained(
        model_id_or_path,
        export=export,
        low_cpu_mem_usage=True,
        # These are parameters required for the conversion
        batch_size=batch_size,
        n_positions=seq_length,
        num_cores=num_cores,
        auto_cast_type=auto_cast_type,
    )


def generate(model, tokenizer, prompts, length, temperature):
    # Specifiy padding options
    tokenizer.pad_token_id = tokenizer.eos_token_id

    # Encode tokens and generate using temperature
    tokens = tokenizer(prompts, return_tensors="pt")
    start = time.time()
    with torch.inference_mode():
        sample_output = model.generate(
            **tokens,
            do_sample=True,
            min_length=length,
            max_length=length,
            temperature=temperature,
        )
    end = time.time()
    outputs = [tokenizer.decode(tok) for tok in sample_output]
    return outputs, (end - start)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=str, help="The HF Hub model id or a local directory.")
    parser.add_argument("--prompt", type=str, default="One of my fondest memory is", help="The starting prompt.")
    parser.add_argument("--length", type=int, default=128, help="The number of tokens in the generated sequences.")
    parser.add_argument(
        "--batch_size", type=int, default=1, help="If > 1, the prompt will be duplicated to test model throughput."
    )
    parser.add_argument(
        "--num_cores", type=int, default=2, help="The number of cores on which the model should be split."
    )
    parser.add_argument("--auto_cast_type", type=str, default="f32", help="One of f32, f16, bf16.")
    parser.add_argument(
        "--temperature",
        type=float,
        default=1.0,
        help="The temperature to generate. 1.0 has no effect, lower tend toward greedy sampling.",
    )
    parser.add_argument(
        "--save_dir", type=str, help="The save directory. Allows to avoid recompiling the model every time."
    )
    parser.add_argument("--compare", action="store_true", help="Compare with the genuine transformers model on CPU.")
    args = parser.parse_args()
    # Load llm model and tokenizer
    model = load_llm_optimum(args.model, args.batch_size, args.length, args.num_cores, args.auto_cast_type)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    # We need to replicate the text if batch_size is not 1
    prompts = [args.prompt for _ in range(args.batch_size)]
    outputs, latency = generate(model, tokenizer, prompts, args.length, args.temperature)
    print(outputs)
    print(f"Outputs generated using Neuron model in {latency:.4f} s")
    if args.compare:
        cpu_model = AutoModelForCausalLM.from_pretrained("gpt2")
        outputs, latency = generate(cpu_model, tokenizer, prompts, args.length, args.temperature)
        print(outputs)
        print(f"Outputs generated using pytorch model in {latency:.4f} s")

    if args.save_dir:
        model.save_pretrained(args.save_dir)
        tokenizer.save_pretrained(args.save_dir)
