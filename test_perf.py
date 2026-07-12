import numpy as np
import time

vectors = np.random.rand(10000, 768)
q = np.random.rand(768)

t0 = time.time()
q_arr = np.array(q)
q_norm = np.linalg.norm(q_arr) or 1e-9

scores = []
for emb in vectors:
    c_arr = np.array(emb)
    c_norm = np.linalg.norm(c_arr) or 1e-9
    sim = np.dot(q_arr, c_arr) / (q_norm * c_norm)
    scores.append(sim)

t1 = time.time()
print("Loop time:", t1-t0)

matrix = np.array(vectors)
norms = np.linalg.norm(matrix, axis=1)

t2 = time.time()
dots = np.dot(matrix, q_arr)
sims = dots / (norms * q_norm)
t3 = time.time()
print("Vectorized time:", t3-t2)
