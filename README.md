# RWKV5-infctxLM
```
python train.py --my_testing r3r4 --load_model /home/asd/model/RWKV-5-World-1B5-v2-20231025-ctx4096.pth --proj_dir /home/asd/model --data_file ttt_text_document --data_type binidx --vocab_size 65536 --epoch_count 100 --epoch_begin 0 --epoch_save 5 --micro_bsz 1 --n_layer 24 --n_embd 2048 --pre_ffn 0 --head_qk 0 --lr_init 1e-5 --lr_final 1e-5 --warmup_steps 0 --beta1 0.9 --beta2 0.99 --adam_eps 1e-8 --accelerator gpu --devices 1 --precision bf16 --strategy deepspeed_stage_2 --grad_cp 1 --real_len 100 --ctx_len 200
```
ctx_len 为你想要的训练长度  4096
real_len 受显存限制为实际训练长度 1024

ttt 测试文件


# training details
python train.py --my_testing r3r4 --load_model /users/aigclab/copilot/Train-infctx-RWKV/models/RWKV-5-World-1B5-v2-20231025-ctx4096.pth --proj_dir out1B5_one_v2_st --data_file /users/aigclab/copilot/Train-infctx-RWKV/data/one_v2_st_text_document --data_type binidx --vocab_size 65536 --epoch_count 100 --epoch_begin 0 --epoch_steps 500 --epoch_save 1 --micro_bsz 16 --n_layer 24 --n_embd 2048 --pre_ffn 0 --head_qk 0 --lr_init 5e-6 --lr_final 1e-6 --warmup_steps 200 --beta1 0.9 --beta2 0.99 --adam_eps 1e-8 --accelerator gpu --devices 1 --precision bf16 --strategy deepspeed_stage_1 --grad_cp 1 --real_len 4096 --ctx_len 16384
