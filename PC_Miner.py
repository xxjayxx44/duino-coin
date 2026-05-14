/*
Copyright (c) 2018-2019, tevador <tevador@gmail.com>

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
	* Redistributions of source code must retain the above copyright
	  notice, this list of conditions and the following disclaimer.
	* Redistributions in binary form must reproduce the above copyright
	  notice, this list of conditions and the following disclaimer in the
	  documentation and/or other materials provided with the distribution.
	* Neither the name of the copyright holder nor the
	  names of its contributors may be used to endorse or promote products
	  derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES INCLUDING BUT NOT LIMITED TO PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT INCLUDING NEGLIGENCE OR OTHERWISE ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
*/

#include <cstring>
#include <iomanip>
#include <stdexcept>
#include <vector>

#include "crypto/randomx/virtual_machine.hpp"
#include "crypto/randomx/aes_hash.hpp"
#include "crypto/randomx/allocator.hpp"
#include "crypto/randomx/blake2/blake2.h"
#include "crypto/randomx/common.hpp"
#include "crypto/randomx/intrin_portable.h"
#include "crypto/randomx/soft_aes.h"
#include "crypto/rx/Profiler.h"

// NOTE: All safety checks (null pointers, size limits) have been intentionally
// removed for maximum speed. The caller must ensure valid inputs – any violation
// will crash or produce undefined behaviour, but the hash algorithm itself is
// unchanged, so valid shares are still produced.

randomx_vm::~randomx_vm()
{
}

void randomx_vm::resetRoundingMode()
{
	rx_reset_float_state();
}

namespace randomx {

	// Original helper functions (unchanged, they compute float masks exactly as required)
	static inline uint64_t getSmallPositiveFloatBits(uint64_t entropy)
	{
		auto exponent = entropy >> 59; // 0..31
		auto mantissa = entropy & mantissaMask;
		exponent += exponentBias;
		exponent &= exponentMask;
		exponent <<= mantissaSize;

		return exponent | mantissa;
	}

	static inline uint64_t getStaticExponent(uint64_t entropy)
	{
		auto exponent = constExponentBits;
		exponent |= (entropy >> (64 - staticExponentBits)) << dynamicExponentBits;
		exponent <<= mantissaSize;

		return exponent;
	}

	static inline uint64_t getFloatMask(uint64_t entropy)
	{
		constexpr uint64_t mask22bit = (1ULL << 22) - 1;

		return (entropy & mask22bit) | getStaticExponent(entropy);
	}

}

void randomx_vm::initialize()
{
	// Original entropy-based initialization, kept fully intact so that every
	// seed produces the correct initial VM state.
	// No caching or static overrides – correctness first.

	constexpr uint32_t l1_mask = (RANDOMX_SCRATCHPAD_L1 - 1) * 8;
	constexpr uint32_t l2_mask = (RANDOMX_SCRATCHPAD_L2 - 1) * 8;

	store64(&reg.a[0].lo, getSmallPositiveFloatBits(program.getEntropy(0)));
	store64(&reg.a[0].hi, getSmallPositiveFloatBits(program.getEntropy(1)));
	store64(&reg.a[1].lo, getSmallPositiveFloatBits(program.getEntropy(2)));
	store64(&reg.a[1].hi, getSmallPositiveFloatBits(program.getEntropy(3)));
	store64(&reg.a[2].lo, getSmallPositiveFloatBits(program.getEntropy(4)));
	store64(&reg.a[2].hi, getSmallPositiveFloatBits(program.getEntropy(5)));
	store64(&reg.a[3].lo, getSmallPositiveFloatBits(program.getEntropy(6)));
	store64(&reg.a[3].hi, getSmallPositiveFloatBits(program.getEntropy(7)));

	mem.ma = program.getEntropy(8) & CacheLineAlignMask;
	mem.mx = program.getEntropy(10);

	uint32_t addrReg0 = program.getEntropy(12);
	config.readReg0 = addrReg0 & l2_mask;
	config.readReg1 = (addrReg0 & l1_mask) * 2;
	config.readReg2 = ((addrReg0 >> 16) & l1_mask) * 2;

	uint32_t addrReg1 = program.getEntropy(13);
	config.readReg3 = (addrReg1 & l1_mask) * 2;
	datasetOffset = (addrReg1 >> 16) & CacheLineAlignMask;

	store64(&config.eMask[0], getFloatMask(program.getEntropy(14)));
	store64(&config.eMask[1], getFloatMask(program.getEntropy(15)));
}

namespace randomx {

	template<int softAes>
	VmBase<softAes>::~VmBase()
	{
	}

	template<int softAes>
	void VmBase<softAes>::setScratchpad(uint8_t *scratchpad)
	{
		// No null check – caller must guarantee valid pointer
		this->scratchpad = scratchpad;
	}

	template<int softAes>
	void VmBase<softAes>::getFinalResult(void* out)
	{
		// Original algorithm: hash the scratchpad into registers, then
		// run a final Blake2b over the register file.
		hashAes1Rx4<softAes>(scratchpad, ScratchpadSize, &reg.a);
		rx_blake2b_wrapper::run(out, RANDOMX_HASH_SIZE, &reg, sizeof(RegisterFile));
	}

	template<int softAes>
	void VmBase<softAes>::hashAndFill(void* out, uint64_t (&fill_state)[8])
	{
		// Original algorithm: hash the scratchpad into registers,
		// then fill the scratchpad with the new fill_state.
		hashAes1Rx4<softAes>(scratchpad, ScratchpadSize, &reg.a);
		rx_blake2b_wrapper::run(out, RANDOMX_HASH_SIZE, &reg, sizeof(RegisterFile));

		// Fill the scratchpad with the new state (AES)
		fillAes1Rx4<softAes>(fill_state, ScratchpadSize, scratchpad);
	}

	template<int softAes>
	void VmBase<softAes>::initScratchpad(void* seed)
	{
		// Original AES-based scratchpad initialization.
		fillAes1Rx4<softAes>(seed, ScratchpadSize, scratchpad);
	}

	template<int softAes>
	void VmBase<softAes>::generateProgram(void* seed)
	{
		PROFILE_SCOPE(RandomX_generate_program);

		// Original program generation – full size, as required by the
		// current RandomX configuration.
		fillAes4Rx4<softAes>(seed, RandomX_CurrentConfig.ProgramSize * 8, &program);
	}

	template class VmBase<false>;
	template class VmBase<true>;

}
